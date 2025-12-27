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
)
from qgis.PyQt.QtGui import QFont
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

            self.progress.emit(f"Authenticating with NASA Earthdata...")
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

        # Granule selection
        granule_layout = QFormLayout()
        self.granule_combo = QComboBox()
        self.granule_combo.setEnabled(False)
        self.granule_combo.currentIndexChanged.connect(self._on_granule_changed)
        granule_layout.addRow("Granule:", self.granule_combo)

        # Layer selection
        self.layer_combo = QComboBox()
        self.layer_combo.setEnabled(False)
        granule_layout.addRow("Layer:", self.layer_combo)

        results_layout.addLayout(granule_layout)

        # Display buttons
        display_btn_layout = QHBoxLayout()

        self.display_single_btn = QPushButton("Display Single")
        self.display_single_btn.setEnabled(False)
        self.display_single_btn.clicked.connect(self._display_single)
        display_btn_layout.addWidget(self.display_single_btn)

        self.display_footprints_btn = QPushButton("Show Footprints")
        self.display_footprints_btn.setEnabled(False)
        self.display_footprints_btn.clicked.connect(self._display_footprints)
        display_btn_layout.addWidget(self.display_footprints_btn)

        results_layout.addLayout(display_btn_layout)

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
        self.output_text.append("Select a granule from the dropdown to display.")

        # Populate granule dropdown
        self.granule_combo.clear()
        self.granule_combo.setEnabled(True)

        for i, result in enumerate(results):
            native_id = result.get("meta", {}).get("native-id", f"Granule {i+1}")
            self.granule_combo.addItem(native_id, i)

        # Enable buttons
        self.display_single_btn.setEnabled(True)
        self.display_footprints_btn.setEnabled(gdf is not None)

    def _on_search_error(self, error_msg):
        """Handle search error."""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        self.status_label.setText("Search failed")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        self.output_text.append(f"\nError: {error_msg}")

        QMessageBox.critical(self, "Search Error", f"Failed to search:\n{error_msg}")

    def _on_granule_changed(self, index):
        """Handle granule selection change."""
        if index < 0 or index >= len(self._results):
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
                self.layer_combo.addItem(filename, link)

        if self.layer_combo.count() == 0:
            self.layer_combo.addItem("No raster files available", None)
            self.layer_combo.setEnabled(False)

    def _display_single(self):
        """Display selected granule layer."""
        if self.layer_combo.count() == 0:
            return

        url = self.layer_combo.currentData()
        if not url:
            QMessageBox.warning(self, "Error", "No valid layer selected")
            return

        # Get the selected granule
        granule_index = self.granule_combo.currentData()
        if granule_index is None or granule_index >= len(self._results):
            QMessageBox.warning(self, "Error", "No valid granule selected")
            return

        granule = self._results[granule_index]
        layer_name = self.layer_combo.currentText().replace(".tif", "")

        self.status_label.setText(f"Downloading {layer_name}...")
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")
        self.output_text.append(f"\nDownloading layer: {layer_name}")

        # Disable buttons during download
        self.display_single_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

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

    def _on_download_progress(self, message):
        """Handle download progress update."""
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_download_finished(self, file_path, layer_name):
        """Handle download completion and add layer to map."""
        self.progress_bar.setVisible(False)
        self.display_single_btn.setEnabled(True)

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
        self.display_single_btn.setEnabled(True)

        self.status_label.setText("Download failed")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        self.output_text.append(f"Error: {error_msg}")

        QMessageBox.critical(
            self, "Download Error", f"Failed to download:\n{error_msg}"
        )

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

        self.granule_combo.clear()
        self.granule_combo.setEnabled(False)
        self.layer_combo.clear()
        self.layer_combo.setEnabled(False)

        self.display_single_btn.setEnabled(False)
        self.display_footprints_btn.setEnabled(False)

        self.output_text.clear()
        self.status_label.setText("Ready to search")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")

        self._results = []
        self._gdf = None

    def closeEvent(self, event):
        """Handle dock widget close event."""
        event.accept()
