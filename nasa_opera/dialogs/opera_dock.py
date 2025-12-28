"""
NASA OPERA Search Dock Widget

This module provides the main NASA OPERA search interface that allows users to:
- Select OPERA dataset products
- Set spatial and temporal filters
- Search and display footprints
- Visualize OPERA raster data in QGIS
"""

import os
import json
import tempfile
from datetime import datetime, date
from typing import Optional, List, Tuple

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QDate, QSettings
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QFormLayout,
    QMessageBox,
    QProgressBar,
    QDateEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QSizePolicy,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)
from qgis.PyQt.QtGui import QFont, QCursor
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsFields,
    QgsWkbTypes,
    QgsMapLayerType,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant


# NASA OPERA datasets
OPERA_DATASETS = {
    "OPERA_L3_DSWX-HLS_V1": {
        "title": "Dynamic Surface Water Extent from Harmonized Landsat Sentinel-2 (Version 1)",
        "short_title": "DSWX-HLS",
        "description": "Surface water extent derived from HLS data",
    },
    "OPERA_L3_DSWX-S1_V1": {
        "title": "Dynamic Surface Water Extent from Sentinel-1 (Version 1)",
        "short_title": "DSWX-S1",
        "description": "Surface water extent derived from Sentinel-1 SAR data",
    },
    "OPERA_L3_DIST-ALERT-HLS_V1": {
        "title": "Land Surface Disturbance Alert from HLS (Version 1)",
        "short_title": "DIST-ALERT",
        "description": "Near real-time disturbance alerts",
    },
    "OPERA_L3_DIST-ANN-HLS_V1": {
        "title": "Land Surface Disturbance Annual from HLS (Version 1)",
        "short_title": "DIST-ANN",
        "description": "Annual land surface disturbance product",
    },
    "OPERA_L2_RTC-S1_V1": {
        "title": "Radiometric Terrain Corrected SAR Backscatter from Sentinel-1 (Version 1)",
        "short_title": "RTC-S1",
        "description": "Analysis-ready SAR backscatter data",
    },
    "OPERA_L2_RTC-S1-STATIC_V1": {
        "title": "RTC-S1 Static Layers (Version 1)",
        "short_title": "RTC-S1-STATIC",
        "description": "Static layers for RTC-S1 product",
    },
    "OPERA_L2_CSLC-S1_V1": {
        "title": "Coregistered Single-Look Complex from Sentinel-1 (Version 1)",
        "short_title": "CSLC-S1",
        "description": "SLC data coregistered to a common reference",
    },
    "OPERA_L2_CSLC-S1-STATIC_V1": {
        "title": "CSLC-S1 Static Layers (Version 1)",
        "short_title": "CSLC-S1-STATIC",
        "description": "Static layers for CSLC-S1 product",
    },
}


class SearchWorker(QThread):
    """Worker thread for searching NASA OPERA data."""

    finished = pyqtSignal(list, object)  # results, gdf or error
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        short_name: str,
        bbox: Optional[Tuple[float, float, float, float]],
        start_date: Optional[str],
        end_date: Optional[str],
        max_items: int,
    ):
        super().__init__()
        self.short_name = short_name
        self.bbox = bbox
        self.start_date = start_date
        self.end_date = end_date
        self.max_items = max_items

    def run(self):
        """Execute the search."""
        try:
            self.progress.emit("Authenticating with NASA Earthdata...")

            import earthaccess

            # Authenticate
            earthaccess.login(persist=True)

            self.progress.emit(f"Searching for {self.short_name}...")

            # Build search parameters
            search_params = {
                "short_name": self.short_name,
                "count": self.max_items,
            }

            if self.bbox:
                search_params["bounding_box"] = self.bbox

            if self.start_date and self.end_date:
                search_params["temporal"] = (self.start_date, self.end_date)
            elif self.start_date:
                search_params["temporal"] = (
                    self.start_date,
                    datetime.today().strftime("%Y-%m-%d"),
                )

            # Search
            results = earthaccess.search_data(**search_params)

            if len(results) == 0:
                self.progress.emit("No results found.")
                self.finished.emit([], None)
                return

            self.progress.emit(f"Found {len(results)} granules. Creating footprints...")

            # Convert to GeoDataFrame
            try:
                import geopandas as gpd
                from shapely.geometry import box, shape, Polygon
                import pandas as pd

                records = []
                for granule in results:
                    record = {
                        "native-id": granule.get("meta", {}).get("native-id", ""),
                        "producer-granule-id": granule.get("meta", {}).get(
                            "producer-granule-id", ""
                        ),
                        "concept-id": granule.get("meta", {}).get("concept-id", ""),
                    }

                    # Get geometry
                    umm = granule.get("umm", {})
                    spatial = umm.get("SpatialExtent", {})
                    horizontal = spatial.get("HorizontalSpatialDomain", {})

                    geometry = None

                    # Try BoundingRectangles first
                    if "Geometry" in horizontal:
                        geo = horizontal["Geometry"]
                        if "BoundingRectangles" in geo:
                            rects = geo["BoundingRectangles"]
                            if rects:
                                r = rects[0]
                                geometry = box(
                                    r.get("WestBoundingCoordinate", 0),
                                    r.get("SouthBoundingCoordinate", 0),
                                    r.get("EastBoundingCoordinate", 0),
                                    r.get("NorthBoundingCoordinate", 0),
                                )
                        elif "GPolygons" in geo:
                            polys = geo["GPolygons"]
                            if polys:
                                boundary = polys[0].get("Boundary", {})
                                points = boundary.get("Points", [])
                                if points:
                                    coords = [
                                        (p.get("Longitude", 0), p.get("Latitude", 0))
                                        for p in points
                                    ]
                                    if coords:
                                        geometry = Polygon(coords)

                    if geometry is None:
                        # Fallback: create a small box
                        geometry = box(-180, -90, 180, 90)

                    record["geometry"] = geometry

                    # Get temporal info
                    temporal = umm.get("TemporalExtent", {})
                    range_dt = temporal.get("RangeDateTime", {})
                    record["begin_date"] = range_dt.get("BeginningDateTime", "")
                    record["end_date"] = range_dt.get("EndingDateTime", "")

                    # Get data links
                    data_links = (
                        granule.data_links() if hasattr(granule, "data_links") else []
                    )
                    record["data_links"] = "|".join(
                        data_links[:5]
                    )  # Store first 5 links
                    record["num_links"] = len(data_links)

                    records.append(record)

                df = pd.DataFrame(records)
                gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

                self.finished.emit(results, gdf)

            except Exception as e:
                # Return results without GeoDataFrame
                self.progress.emit(f"Warning: Could not create GeoDataFrame: {str(e)}")
                self.finished.emit(results, None)

        except Exception as e:
            self.error.emit(str(e))


class DownloadRasterWorker(QThread):
    """Worker thread for downloading and loading raster data."""

    finished = pyqtSignal(str, str)  # file_path, layer_name
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, granule, url: str, layer_name: str, download_dir: str):
        super().__init__()
        self.granule = granule
        self.url = url
        self.layer_name = layer_name
        self.download_dir = download_dir

    def run(self):
        """Download and prepare the raster data."""
        try:
            import earthaccess

            self.progress.emit("Authenticating with NASA Earthdata...")
            earthaccess.login(persist=True)

            self.progress.emit(f"Downloading {self.layer_name}...")

            # Create download directory if it doesn't exist
            os.makedirs(self.download_dir, exist_ok=True)

            # Download the specific file using earthaccess
            # We need to filter for the specific URL we want
            filename = self.url.split("/")[-1]
            local_path = os.path.join(self.download_dir, filename)

            # Check if file already exists
            if os.path.exists(local_path):
                self.progress.emit(f"Using cached file: {filename}")
                self.finished.emit(local_path, self.layer_name)
                return

            # Download using earthaccess - download all files for the granule and find our file
            downloaded_files = earthaccess.download(
                [self.granule], local_path=self.download_dir, threads=1
            )

            # Find the downloaded file
            if downloaded_files:
                for f in downloaded_files:
                    if isinstance(f, str) and f.endswith(filename):
                        self.finished.emit(f, self.layer_name)
                        return
                    elif hasattr(f, "name") and str(f).endswith(filename):
                        self.finished.emit(str(f), self.layer_name)
                        return

                # If we couldn't find the exact file, try to find any matching tif
                for f in downloaded_files:
                    f_str = str(f) if not isinstance(f, str) else f
                    if f_str.endswith(".tif"):
                        self.finished.emit(f_str, self.layer_name)
                        return

                # Return first downloaded file as fallback
                first_file = (
                    str(downloaded_files[0])
                    if not isinstance(downloaded_files[0], str)
                    else downloaded_files[0]
                )
                self.finished.emit(first_file, self.layer_name)
            else:
                self.error.emit("No files were downloaded")

        except Exception as e:
            self.error.emit(str(e))


def setup_gdal_for_earthdata():
    """Configure GDAL environment for accessing NASA Earthdata via S3.

    Returns:
        tuple: (success, vsicurl_prefix) or (False, error_message)
    """
    try:
        import earthaccess
        from osgeo import gdal

        # Authenticate and get S3 credentials
        earthaccess.login(persist=True)
        s3_credentials = earthaccess.get_s3_credentials(daac="PODAAC")

        # Configure GDAL for S3 access
        gdal.SetConfigOption("AWS_ACCESS_KEY_ID", s3_credentials["accessKeyId"])
        gdal.SetConfigOption("AWS_SECRET_ACCESS_KEY", s3_credentials["secretAccessKey"])
        gdal.SetConfigOption("AWS_SESSION_TOKEN", s3_credentials["sessionToken"])
        gdal.SetConfigOption("AWS_REGION", "us-west-2")
        gdal.SetConfigOption("AWS_S3_ENDPOINT", "s3.us-west-2.amazonaws.com")
        gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
        gdal.SetConfigOption(
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.tiff,.TIFF"
        )
        gdal.SetConfigOption("GDAL_HTTP_UNSAFESSL", "YES")
        gdal.SetConfigOption(
            "GDAL_HTTP_COOKIEFILE", os.path.expanduser("~/cookies.txt")
        )
        gdal.SetConfigOption("GDAL_HTTP_COOKIEJAR", os.path.expanduser("~/cookies.txt"))

        return True, None

    except Exception as e:
        return False, str(e)


def get_vsicurl_path(url: str) -> str:
    """Convert an S3 or HTTPS URL to a GDAL VSICURL/VSIS3 path.

    Args:
        url: The S3 or HTTPS URL to the file

    Returns:
        The VSICURL or VSIS3 path for GDAL
    """
    if url.startswith("s3://"):
        # Use VSIS3 for direct S3 access (requires credentials)
        return f"/vsis3/{url[5:]}"
    elif url.startswith("https://"):
        # Use VSICURL for HTTPS access
        return f"/vsicurl/{url}"
    elif url.startswith("http://"):
        return f"/vsicurl/{url}"
    else:
        return url


class OperaDockWidget(QDockWidget):
    """NASA OPERA search and visualization dock widget."""

    def __init__(self, iface, parent=None):
        """Initialize the dock widget.

        Args:
            iface: QGIS interface instance.
            parent: Parent widget.
        """
        super().__init__("NASA OPERA Search", parent)
        self.iface = iface
        self.settings = QSettings()

        # Storage for search results
        self._results = []
        self._gdf = None
        self._footprint_layer = None

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dock widget UI."""
        # Main widget
        main_widget = QWidget()
        self.setWidget(main_widget)

        # Main layout
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header_label = QLabel("NASA OPERA Data Search")
        header_font = QFont()
        header_font.setPointSize(11)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet("color: #1565C0; padding: 5px;")
        layout.addWidget(header_label)

        # Dataset selection group
        dataset_group = QGroupBox("Dataset")
        dataset_layout = QFormLayout(dataset_group)
        dataset_layout.setSpacing(6)

        # Dataset dropdown
        self.dataset_combo = QComboBox()
        for short_name, info in OPERA_DATASETS.items():
            self.dataset_combo.addItem(
                f"{info['short_title']} - {short_name}", short_name
            )
        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        dataset_layout.addRow("Product:", self.dataset_combo)

        # Dataset description
        self.dataset_desc_label = QLabel()
        self.dataset_desc_label.setWordWrap(True)
        self.dataset_desc_label.setStyleSheet("color: gray; font-size: 10px;")
        dataset_layout.addRow(self.dataset_desc_label)

        layout.addWidget(dataset_group)

        # Search parameters group
        search_group = QGroupBox("Search Parameters")
        search_layout = QFormLayout(search_group)
        search_layout.setSpacing(6)

        # Max items
        self.max_items_spin = QSpinBox()
        self.max_items_spin.setRange(1, 500)
        self.max_items_spin.setValue(50)
        search_layout.addRow("Max Results:", self.max_items_spin)

        # Bounding box
        self.bbox_input = QLineEdit()
        self.bbox_input.setPlaceholderText("xmin, ymin, xmax, ymax (or use map extent)")
        search_layout.addRow("Bounding Box:", self.bbox_input)

        # Use map extent button
        bbox_btn_layout = QHBoxLayout()
        self.use_extent_btn = QPushButton("Use Map Extent")
        self.use_extent_btn.clicked.connect(self._use_map_extent)
        self.clear_bbox_btn = QPushButton("Clear")
        self.clear_bbox_btn.clicked.connect(lambda: self.bbox_input.clear())
        bbox_btn_layout.addWidget(self.use_extent_btn)
        bbox_btn_layout.addWidget(self.clear_bbox_btn)
        search_layout.addRow("", bbox_btn_layout)

        # Date range
        date_layout = QHBoxLayout()

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        date_layout.addWidget(QLabel("From:"))
        date_layout.addWidget(self.start_date_edit)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        date_layout.addWidget(QLabel("To:"))
        date_layout.addWidget(self.end_date_edit)

        search_layout.addRow("Date Range:", date_layout)

        layout.addWidget(search_group)

        # Search button
        search_btn_layout = QHBoxLayout()
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1976D2;
                color: white;
                font-weight: bold;
                padding: 4px 12px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1565C0;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """
        )
        self.search_btn.clicked.connect(self._search)
        search_btn_layout.addWidget(self.search_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        search_btn_layout.addWidget(self.reset_btn)

        layout.addLayout(search_btn_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready to search")
        self.status_label.setStyleSheet("color: gray; font-size: 10px; padding: 2px;")
        layout.addWidget(self.status_label)

        # Results group
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        results_layout.setSpacing(4)

        # Granule list with multi-select
        granule_label = QLabel("Granules (select one or more):")
        results_layout.addWidget(granule_label)

        self.granule_list = QListWidget()
        self.granule_list.setEnabled(False)
        self.granule_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.granule_list.setMaximumHeight(100)
        self.granule_list.itemSelectionChanged.connect(
            self._on_granule_selection_changed
        )
        results_layout.addWidget(self.granule_list)

        # Select all / Deselect all buttons
        select_btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.clicked.connect(self._select_all_granules)
        select_btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.setEnabled(False)
        self.deselect_all_btn.clicked.connect(self._deselect_all_granules)
        select_btn_layout.addWidget(self.deselect_all_btn)
        results_layout.addLayout(select_btn_layout)

        # Layer selection
        layer_layout = QFormLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.setEnabled(False)
        layer_layout.addRow("Layer:", self.layer_combo)
        results_layout.addLayout(layer_layout)

        # Display buttons - row 1
        display_btn_layout1 = QHBoxLayout()

        self.display_single_btn = QPushButton("Display Single")
        self.display_single_btn.setEnabled(False)
        self.display_single_btn.clicked.connect(self._display_single)
        display_btn_layout1.addWidget(self.display_single_btn)

        self.display_footprints_btn = QPushButton("Show Footprints")
        self.display_footprints_btn.setEnabled(False)
        self.display_footprints_btn.clicked.connect(self._display_footprints)
        display_btn_layout1.addWidget(self.display_footprints_btn)

        results_layout.addLayout(display_btn_layout1)

        # Display buttons - row 2 (Mosaic)
        display_btn_layout2 = QHBoxLayout()

        self.display_mosaic_btn = QPushButton("Display Mosaic")
        self.display_mosaic_btn.setEnabled(False)
        self.display_mosaic_btn.setToolTip(
            "Create a virtual mosaic from selected granules"
        )
        self.display_mosaic_btn.clicked.connect(self._display_mosaic)
        display_btn_layout2.addWidget(self.display_mosaic_btn)

        results_layout.addLayout(display_btn_layout2)

        layout.addWidget(results_group)

        # Output area
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMaximumHeight(120)
        self.output_text.setPlaceholderText(
            "Search results and status messages will appear here..."
        )
        self.output_text.setStyleSheet("font-family: monospace; font-size: 10px;")
        output_layout.addWidget(self.output_text)

        layout.addWidget(output_group)

        # Stretch at the end
        layout.addStretch()

        # Initialize dataset description
        self._on_dataset_changed(0)

    def _on_dataset_changed(self, index):
        """Handle dataset selection change."""
        short_name = self.dataset_combo.currentData()
        if short_name and short_name in OPERA_DATASETS:
            info = OPERA_DATASETS[short_name]
            self.dataset_desc_label.setText(info["description"])

    def _use_map_extent(self):
        """Use current map extent as bounding box."""
        try:
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()

            # Transform to WGS84
            source_crs = canvas.mapSettings().destinationCrs()
            dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")

            if source_crs != dest_crs:
                transform = QgsCoordinateTransform(
                    source_crs, dest_crs, QgsProject.instance()
                )
                extent = transform.transformBoundingBox(extent)

            bbox_str = f"{extent.xMinimum():.6f}, {extent.yMinimum():.6f}, {extent.xMaximum():.6f}, {extent.yMaximum():.6f}"
            self.bbox_input.setText(bbox_str)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to get map extent: {str(e)}")

    def _search(self):
        """Execute the search."""
        # Get parameters
        short_name = self.dataset_combo.currentData()
        max_items = self.max_items_spin.value()

        # Parse bounding box
        bbox = None
        bbox_text = self.bbox_input.text().strip()
        if bbox_text:
            try:
                parts = [float(x.strip()) for x in bbox_text.split(",")]
                if len(parts) == 4:
                    bbox = tuple(parts)
                else:
                    QMessageBox.warning(
                        self,
                        "Error",
                        "Bounding box must have 4 values: xmin, ymin, xmax, ymax",
                    )
                    return
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid bounding box format")
                return

        # Get dates
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        # Disable UI during search
        self.search_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")
        self.output_text.clear()

        # Create and start worker
        self._search_worker = SearchWorker(
            short_name=short_name,
            bbox=bbox,
            start_date=start_date,
            end_date=end_date,
            max_items=max_items,
        )
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.progress.connect(self._on_search_progress)
        self._search_worker.start()

    def _on_search_progress(self, message):
        """Handle search progress update."""
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_search_finished(self, results, gdf):
        """Handle search completion."""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        self._results = results
        self._gdf = gdf

        if len(results) == 0:
            self.status_label.setText("No results found")
            self.status_label.setStyleSheet("color: orange; font-size: 10px;")
            self.output_text.append("No granules found matching the search criteria.")
            return

        self.status_label.setText(f"Found {len(results)} granules")
        self.status_label.setStyleSheet("color: green; font-size: 10px;")
        self.output_text.append(f"\nFound {len(results)} granules.")
        self.output_text.append("Select granule(s) from the list to display.")

        # Populate granule list
        self.granule_list.clear()
        self.granule_list.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)

        for i, result in enumerate(results):
            native_id = result.get("meta", {}).get("native-id", f"Granule {i+1}")
            item = QListWidgetItem(native_id)
            item.setData(Qt.UserRole, i)  # Store index
            self.granule_list.addItem(item)

        # Select first item by default
        if self.granule_list.count() > 0:
            self.granule_list.item(0).setSelected(True)

        # Enable buttons
        self.display_footprints_btn.setEnabled(gdf is not None)

    def _on_search_error(self, error_msg):
        """Handle search error."""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        self.status_label.setText("Search failed")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        self.output_text.append(f"\nError: {error_msg}")

        QMessageBox.critical(self, "Search Error", f"Failed to search:\n{error_msg}")

    def _on_granule_selection_changed(self):
        """Handle granule selection change in the list widget."""
        selected_items = self.granule_list.selectedItems()
        num_selected = len(selected_items)

        # Enable/disable buttons based on selection
        self.display_single_btn.setEnabled(num_selected == 1)
        self.display_mosaic_btn.setEnabled(num_selected >= 1)

        if num_selected == 0:
            self.layer_combo.clear()
            self.layer_combo.setEnabled(False)
            return

        # Get the first selected granule to populate layer dropdown
        first_item = selected_items[0]
        index = first_item.data(Qt.UserRole)

        if index is None or index >= len(self._results):
            return

        result = self._results[index]

        # Get data links
        data_links = result.data_links() if hasattr(result, "data_links") else []

        # Populate layer dropdown with available files
        self.layer_combo.clear()
        self.layer_combo.setEnabled(True)

        for link in data_links:
            # Get filename from URL
            filename = link.split("/")[-1]
            if filename.endswith(".tif") or filename.endswith(".h5"):
                # Store just the layer suffix (e.g., B01_WTR.tif)
                self.layer_combo.addItem(filename, link)

        if self.layer_combo.count() == 0:
            self.layer_combo.addItem("No raster files available", None)
            self.layer_combo.setEnabled(False)

    def _select_all_granules(self):
        """Select all granules in the list."""
        self.granule_list.selectAll()

    def _deselect_all_granules(self):
        """Deselect all granules in the list."""
        self.granule_list.clearSelection()

    def _display_single(self):
        """Display selected granule layer."""
        if self.layer_combo.count() == 0:
            return

        url = self.layer_combo.currentData()
        if not url:
            QMessageBox.warning(self, "Error", "No valid layer selected")
            return

        # Get the selected granule from the list
        selected_items = self.granule_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No granule selected")
            return

        granule_index = selected_items[0].data(Qt.UserRole)
        if granule_index is None or granule_index >= len(self._results):
            QMessageBox.warning(self, "Error", "No valid granule selected")
            return

        granule = self._results[granule_index]
        layer_name = self.layer_combo.currentText().replace(".tif", "")

        # Check if it's a COG (GeoTIFF) file - try streaming first
        is_tif = url.lower().endswith((".tif", ".tiff"))

        if is_tif:
            # Show waiting state
            self._set_busy_state(True)
            self.status_label.setText(f"Loading COG: {layer_name}...")
            self.status_label.setStyleSheet("color: blue; font-size: 10px;")
            self.output_text.append(f"\nTrying to stream COG: {layer_name}")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            QApplication.processEvents()  # Update UI

            # Try cloud access first
            success = self._try_load_cog(url, layer_name)

            if success:
                self._set_busy_state(False)
                self.progress_bar.setVisible(False)
                return  # Successfully loaded via cloud access

            # If cloud access failed, fall back to download
            self.output_text.append("Cloud access failed, falling back to download...")
            QApplication.processEvents()

        # For non-COG files or if COG access failed, download the file
        self._set_busy_state(True)
        self.status_label.setText(f"Downloading {layer_name}...")
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")
        self.output_text.append(f"Downloading layer: {layer_name}")

        # Disable buttons during download
        self.display_single_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        # Get download directory from settings or use temp
        download_dir = self.settings.value("NasaOpera/cache_dir", "")
        if not download_dir:
            download_dir = os.path.join(tempfile.gettempdir(), "nasa_opera_cache")

        # Create and start download worker
        self._download_worker = DownloadRasterWorker(
            granule=granule,
            url=url,
            layer_name=layer_name,
            download_dir=download_dir,
        )
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.start()

    def _set_busy_state(self, busy: bool):
        """Set the UI to busy/waiting state.

        Args:
            busy: True to show waiting cursor, False to restore normal cursor
        """
        if busy:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
            self.display_single_btn.setEnabled(False)
            self.display_footprints_btn.setEnabled(False)
            self.display_mosaic_btn.setEnabled(False)
        else:
            QApplication.restoreOverrideCursor()
            # Re-enable buttons based on selection state
            selected_items = self.granule_list.selectedItems()
            self.display_single_btn.setEnabled(len(selected_items) == 1)
            self.display_mosaic_btn.setEnabled(len(selected_items) >= 1)
            self.display_footprints_btn.setEnabled(self._gdf is not None)

    def _try_load_cog(self, url: str, layer_name: str) -> bool:
        """Try to load a Cloud-Optimized GeoTIFF directly via streaming.

        Args:
            url: The URL to the COG file
            layer_name: The name for the layer

        Returns:
            True if successful, False otherwise
        """
        try:
            # Setup GDAL for Earthdata access
            self.status_label.setText("Setting up cloud access...")
            QApplication.processEvents()

            success, error = setup_gdal_for_earthdata()
            if not success:
                self.output_text.append(f"Failed to setup cloud access: {error}")
                return False

            # Get the VSICURL/VSIS3 path
            vsi_path = get_vsicurl_path(url)
            self.output_text.append(f"Trying: {vsi_path}")

            self.status_label.setText(f"Streaming COG: {layer_name}...")
            QApplication.processEvents()

            # Try to create the raster layer
            layer = QgsRasterLayer(vsi_path, layer_name)

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

                # Zoom to layer extent with CRS transformation
                layer_extent = layer.extent()
                layer_crs = layer.crs()
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

                if (
                    layer_crs.isValid()
                    and canvas_crs.isValid()
                    and layer_crs != canvas_crs
                ):
                    transform = QgsCoordinateTransform(
                        layer_crs, canvas_crs, QgsProject.instance()
                    )
                    layer_extent = transform.transformBoundingBox(layer_extent)

                self.iface.mapCanvas().setExtent(layer_extent)
                self.iface.mapCanvas().refresh()

                self.status_label.setText(f"Loaded (streaming): {layer_name}")
                self.status_label.setStyleSheet("color: green; font-size: 10px;")
                self.output_text.append(f"Successfully loaded COG via cloud streaming!")
                return True
            else:
                self.output_text.append("Layer not valid via cloud access")
                return False

        except Exception as e:
            self.output_text.append(f"Cloud access error: {str(e)}")
            return False

    def _on_download_progress(self, message):
        """Handle download progress update."""
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_download_finished(self, file_path, layer_name):
        """Handle download completion and add layer to map."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        try:
            # Add raster layer from local file
            layer = QgsRasterLayer(file_path, layer_name)

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

                # Zoom to layer extent with CRS transformation
                layer_extent = layer.extent()
                layer_crs = layer.crs()
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

                if (
                    layer_crs.isValid()
                    and canvas_crs.isValid()
                    and layer_crs != canvas_crs
                ):
                    transform = QgsCoordinateTransform(
                        layer_crs, canvas_crs, QgsProject.instance()
                    )
                    layer_extent = transform.transformBoundingBox(layer_extent)

                self.iface.mapCanvas().setExtent(layer_extent)
                self.iface.mapCanvas().refresh()

                self.status_label.setText(f"Loaded: {layer_name}")
                self.status_label.setStyleSheet("color: green; font-size: 10px;")
                self.output_text.append(f"Successfully loaded layer: {layer_name}")
                self.output_text.append(f"File: {file_path}")
            else:
                raise Exception(f"Layer is not valid: {file_path}")

        except Exception as e:
            self.status_label.setText("Failed to load layer")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.output_text.append(f"Error loading layer: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load layer:\n{str(e)}")

    def _on_download_error(self, error_msg):
        """Handle download error."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        self.status_label.setText("Download failed")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        self.output_text.append(f"Error: {error_msg}")

        QMessageBox.critical(
            self, "Download Error", f"Failed to download:\n{error_msg}"
        )

    def _display_mosaic(self):
        """Display a virtual mosaic from selected granules.

        Creates separate mosaics for each projection/UTM zone to ensure proper alignment.
        """
        selected_items = self.granule_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No granules selected")
            return

        if len(selected_items) < 1:
            QMessageBox.warning(self, "Error", "Select at least one granule for mosaic")
            return

        # Get the selected layer type - extract just the layer suffix (e.g., B01_WTR.tif)
        layer_filename = self.layer_combo.currentText()
        if not layer_filename or layer_filename == "No raster files available":
            QMessageBox.warning(self, "Error", "No layer type selected")
            return

        # Extract the layer band identifier from the filename
        # OPERA filenames follow pattern: OPERA_L3_DSWx-HLS_T12STF_..._v1.1_B01_WTR.tif
        # We want to extract "B01_WTR" to match across different granules
        import re

        # Try to extract the band identifier (e.g., "B01_WTR", "B02_BWTR", etc.)
        # Pattern: _B followed by digits, then underscore, then letters, then .tif
        match = re.search(r"_(B\d+_[A-Za-z0-9]+)\.tif$", layer_filename, re.IGNORECASE)
        if match:
            layer_band = match.group(1)  # e.g., "B01_WTR"
        else:
            # Fallback: try to get the last two underscore-separated parts before .tif
            parts = layer_filename.replace(".tif", "").split("_")
            if len(parts) >= 2:
                layer_band = "_".join(parts[-2:])  # e.g., "B01_WTR"
            else:
                layer_band = parts[-1] if parts else layer_filename

        # Show busy state
        self._set_busy_state(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(
            f"Creating mosaic from {len(selected_items)} granules..."
        )
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")
        self.output_text.append(
            f"\nCreating mosaic from {len(selected_items)} granules..."
        )
        self.output_text.append(f"Layer band: {layer_band}")
        QApplication.processEvents()

        try:
            from osgeo import gdal, osr

            # Setup GDAL for Earthdata access
            self.output_text.append("Setting up cloud access...")
            QApplication.processEvents()

            success, error = setup_gdal_for_earthdata()
            if not success:
                raise Exception(f"Failed to setup cloud access: {error}")

            # Enable GDAL errors for debugging
            gdal.UseExceptions()

            # Collect URLs for all selected granules, grouped by CRS
            # Dictionary: CRS WKT -> list of (vsi_path, crs_name)
            files_by_crs = {}
            not_found = []
            access_failed = []

            total_granules = len(selected_items)
            for idx, item in enumerate(selected_items):
                granule_index = item.data(Qt.UserRole)
                if granule_index is None or granule_index >= len(self._results):
                    continue

                granule = self._results[granule_index]
                granule_id = item.text()
                data_links = (
                    granule.data_links() if hasattr(granule, "data_links") else []
                )

                self.status_label.setText(
                    f"Checking file {idx + 1}/{total_granules}..."
                )
                QApplication.processEvents()

                # Find the matching layer file by band identifier
                found = False
                for link in data_links:
                    # Check if this link contains our band identifier followed by .tif
                    # Use case-insensitive matching
                    if (
                        f"_{layer_band}.tif".lower() in link.lower()
                        or link.lower().endswith(f"{layer_band}.tif".lower())
                    ):
                        vsi_path = get_vsicurl_path(link)

                        # Verify the file is accessible and get its CRS
                        try:
                            ds = gdal.Open(vsi_path)
                            if ds is not None:
                                # Get the CRS
                                proj = ds.GetProjection()
                                srs = osr.SpatialReference()
                                srs.ImportFromWkt(proj)

                                # Get a readable CRS name (e.g., "UTM zone 12N")
                                crs_name = (
                                    srs.GetName() if srs.GetName() else "Unknown CRS"
                                )
                                # Extract just the zone info for cleaner naming
                                zone_match = re.search(
                                    r"(UTM zone \d+[NS]?)", crs_name, re.IGNORECASE
                                )
                                if zone_match:
                                    crs_short = zone_match.group(1)
                                else:
                                    crs_short = crs_name[:30]

                                # Use EPSG code as key if available, otherwise use WKT
                                epsg = srs.GetAuthorityCode(None)
                                if epsg:
                                    crs_key = f"EPSG:{epsg}"
                                else:
                                    crs_key = proj[:100]  # Use truncated WKT as key

                                # Group by CRS
                                if crs_key not in files_by_crs:
                                    files_by_crs[crs_key] = {
                                        "name": crs_short,
                                        "paths": [],
                                    }
                                files_by_crs[crs_key]["paths"].append(vsi_path)

                                self.output_text.append(
                                    f"  [{idx + 1}] OK: {os.path.basename(link)} ({crs_short})"
                                )
                                ds = None  # Close dataset
                                found = True
                            else:
                                access_failed.append(os.path.basename(link))
                                self.output_text.append(
                                    f"  [{idx + 1}] FAILED: {os.path.basename(link)} (cannot open)"
                                )
                        except Exception as e:
                            access_failed.append(os.path.basename(link))
                            self.output_text.append(
                                f"  [{idx + 1}] FAILED: {os.path.basename(link)} ({str(e)[:50]})"
                            )
                        break

                if not found and granule_id not in [
                    f[:30] + "..." for f in access_failed
                ]:
                    not_found.append(granule_id[:40])
                    self.output_text.append(
                        f"  [{idx + 1}] NOT FOUND: No {layer_band} in granule"
                    )

                QApplication.processEvents()

            if not_found:
                self.output_text.append(
                    f"\nWarning: {len(not_found)} granules missing layer {layer_band}"
                )
            if access_failed:
                self.output_text.append(
                    f"Warning: {len(access_failed)} files failed to open"
                )

            total_files = sum(len(v["paths"]) for v in files_by_crs.values())
            if total_files == 0:
                raise Exception("No accessible files found for selected granules")

            self.output_text.append(
                f"\nSuccessfully verified {total_files} of {total_granules} files"
            )
            self.output_text.append(
                f"Found {len(files_by_crs)} different projection(s)"
            )
            QApplication.processEvents()

            # Create separate VRT for each CRS group
            temp_dir = tempfile.gettempdir()
            layers_created = []
            combined_extent = None

            for crs_idx, (crs_key, crs_data) in enumerate(files_by_crs.items()):
                crs_name = crs_data["name"]
                vsi_paths = crs_data["paths"]

                self.status_label.setText(
                    f"Building mosaic {crs_idx + 1}/{len(files_by_crs)} ({crs_name})..."
                )
                self.output_text.append(
                    f"\nBuilding mosaic for {crs_name} ({len(vsi_paths)} files)..."
                )
                QApplication.processEvents()

                # Create VRT for this CRS group
                vrt_filename = (
                    f"opera_mosaic_{crs_name.replace(' ', '_').replace('/', '_')}.vrt"
                )
                vrt_path = os.path.join(temp_dir, vrt_filename)

                vrt_options = gdal.BuildVRTOptions(
                    resampleAlg="nearest",
                    addAlpha=False,
                    srcNodata=255,
                    VRTNodata=255,
                )

                vrt_ds = gdal.BuildVRT(vrt_path, vsi_paths, options=vrt_options)
                if vrt_ds is None:
                    gdal_error = gdal.GetLastErrorMsg()
                    self.output_text.append(
                        f"  Warning: Failed to build VRT for {crs_name}: {gdal_error}"
                    )
                    continue

                # Get VRT info
                vrt_width = vrt_ds.RasterXSize
                vrt_height = vrt_ds.RasterYSize
                vrt_ds.FlushCache()
                vrt_ds = None

                self.output_text.append(
                    f"  VRT created: {vrt_width}x{vrt_height} pixels"
                )

                # Load VRT as raster layer
                layer_name = f"OPERA Mosaic - {crs_name} ({len(vsi_paths)} scenes)"
                layer = QgsRasterLayer(vrt_path, layer_name)

                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    layers_created.append(layer)

                    # Track combined extent (transform to canvas CRS)
                    layer_extent = layer.extent()
                    layer_crs = layer.crs()
                    canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

                    if (
                        layer_crs.isValid()
                        and canvas_crs.isValid()
                        and layer_crs != canvas_crs
                    ):
                        transform = QgsCoordinateTransform(
                            layer_crs, canvas_crs, QgsProject.instance()
                        )
                        layer_extent = transform.transformBoundingBox(layer_extent)

                    if combined_extent is None:
                        combined_extent = QgsRectangle(layer_extent)
                    else:
                        combined_extent.combineExtentWith(layer_extent)

                    self.output_text.append(f"  Layer added: {layer_name}")
                else:
                    self.output_text.append(
                        f"  Warning: Failed to load VRT layer for {crs_name}"
                    )

                QApplication.processEvents()

            if not layers_created:
                raise Exception("Failed to create any mosaic layers")

            # Zoom to combined extent
            if combined_extent:
                combined_extent.scale(1.05)  # Add 5% buffer
                self.iface.mapCanvas().setExtent(combined_extent)
                self.iface.mapCanvas().refresh()

            self.status_label.setText(f"Created {len(layers_created)} mosaic layer(s)")
            self.status_label.setStyleSheet("color: green; font-size: 10px;")
            self.output_text.append(
                f"\nSuccessfully created {len(layers_created)} mosaic layer(s) with {total_files} scenes total!"
            )

        except Exception as e:
            self.status_label.setText("Mosaic failed")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.output_text.append(f"\nError creating mosaic: {str(e)}")
            QMessageBox.critical(
                self, "Mosaic Error", f"Failed to create mosaic:\n{str(e)}"
            )

        finally:
            self._set_busy_state(False)
            self.progress_bar.setVisible(False)

    def _display_footprints(self):
        """Display search result footprints as a vector layer."""
        if self._gdf is None:
            QMessageBox.warning(self, "Error", "No footprint data available")
            return

        try:
            # Remove existing footprint layer
            if self._footprint_layer and self._footprint_layer.id() in [
                l.id() for l in QgsProject.instance().mapLayers().values()
            ]:
                QgsProject.instance().removeMapLayer(self._footprint_layer.id())

            # Create a temporary GeoJSON file
            temp_dir = tempfile.gettempdir()
            geojson_path = os.path.join(temp_dir, "opera_footprints.geojson")

            # Save GeoDataFrame to GeoJSON
            self._gdf.to_file(geojson_path, driver="GeoJSON")

            # Create and add vector layer
            layer_name = f"OPERA Footprints ({len(self._gdf)})"
            layer = QgsVectorLayer(geojson_path, layer_name, "ogr")

            if layer.isValid():
                # Style the layer
                from qgis.core import QgsSimpleFillSymbolLayer, QgsFillSymbol

                symbol = QgsFillSymbol.createSimple(
                    {
                        "color": "65,105,225,50",  # Royal blue with transparency
                        "outline_color": "65,105,225,255",
                        "outline_width": "0.5",
                    }
                )
                layer.renderer().setSymbol(symbol)

                QgsProject.instance().addMapLayer(layer)
                self._footprint_layer = layer

                # Zoom to layer extent with proper CRS transformation
                layer_extent = layer.extent()
                layer_crs = layer.crs()
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

                if layer_crs != canvas_crs:
                    transform = QgsCoordinateTransform(
                        layer_crs, canvas_crs, QgsProject.instance()
                    )
                    layer_extent = transform.transformBoundingBox(layer_extent)

                # Add a small buffer to the extent for better visibility
                layer_extent.scale(1.1)
                self.iface.mapCanvas().setExtent(layer_extent)
                self.iface.mapCanvas().refresh()

                self.status_label.setText(f"Displayed {len(self._gdf)} footprints")
                self.status_label.setStyleSheet("color: green; font-size: 10px;")
                self.output_text.append(f"Displayed {len(self._gdf)} footprints on map")
            else:
                raise Exception("Failed to create footprint layer")

        except Exception as e:
            self.status_label.setText("Failed to display footprints")
            self.status_label.setStyleSheet("color: red; font-size: 10px;")
            self.output_text.append(f"Error: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to display footprints:\n{str(e)}"
            )

    def _reset(self):
        """Reset the search interface."""
        self.bbox_input.clear()
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.end_date_edit.setDate(QDate.currentDate())
        self.max_items_spin.setValue(50)
        self.dataset_combo.setCurrentIndex(0)

        self.granule_list.clear()
        self.granule_list.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.deselect_all_btn.setEnabled(False)
        self.layer_combo.clear()
        self.layer_combo.setEnabled(False)

        self.display_single_btn.setEnabled(False)
        self.display_footprints_btn.setEnabled(False)
        self.display_mosaic_btn.setEnabled(False)

        self.output_text.clear()
        self.status_label.setText("Ready to search")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")

        self._results = []
        self._gdf = None

    def closeEvent(self, event):
        """Handle dock widget close event."""
        event.accept()
