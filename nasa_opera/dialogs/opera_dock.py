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
import math
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
    QAbstractItemView,
    QFileDialog,
)
from qgis.PyQt.QtGui import QFont, QCursor, QColor
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
    QgsPointXY,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

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


class DownloadGranulesWorker(QThread):
    """Worker thread for downloading multiple granules' data files."""

    progress = pyqtSignal(str)
    file_downloaded = pyqtSignal(str, int, int)  # file_path, current, total
    finished = pyqtSignal(list)  # list of downloaded file paths
    error = pyqtSignal(str)

    def __init__(self, granules, download_dir, layer_filter=None):
        """Initialize the download worker.

        Args:
            granules: List of earthaccess granule objects to download.
            download_dir: Directory path to save downloaded files.
            layer_filter: Optional layer band suffix to filter downloads
                (e.g. "B01_WTR"). When set, only files matching this band
                are downloaded. When None, all files are downloaded.
        """
        super().__init__()
        self.granules = granules
        self.download_dir = download_dir
        self.layer_filter = layer_filter
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the download."""
        self._cancelled = True

    def run(self):
        """Execute the download of all granules."""
        try:
            import earthaccess

            self.progress.emit("Authenticating with NASA Earthdata...")
            earthaccess.login(persist=True)

            os.makedirs(self.download_dir, exist_ok=True)

            all_downloaded = []
            total = len(self.granules)

            if self.layer_filter:
                # Single-layer mode: collect matching URLs, download them directly
                urls = []
                for i, granule in enumerate(self.granules):
                    granule_id = granule.get("meta", {}).get(
                        "native-id", f"Granule {i + 1}"
                    )
                    data_links = (
                        granule.data_links() if hasattr(granule, "data_links") else []
                    )
                    found = False
                    for link in data_links:
                        if (
                            f"_{self.layer_filter}.tif".lower() in link.lower()
                            or link.lower().endswith(
                                f"_{self.layer_filter}.tif".lower()
                            )
                        ):
                            urls.append(link)
                            found = True
                            break
                    if not found:
                        self.progress.emit(
                            f"  Warning: No {self.layer_filter} layer "
                            f"found for {granule_id}"
                        )

                if not urls:
                    self.error.emit(
                        f"No {self.layer_filter} files found in selected granules"
                    )
                    return

                if self._cancelled:
                    self.progress.emit("Download cancelled by user.")
                    self.finished.emit(all_downloaded)
                    return

                self.progress.emit(f"Downloading {len(urls)} files...")
                downloaded = earthaccess.download(
                    urls, local_path=self.download_dir, threads=1
                )
                for i, f in enumerate(downloaded):
                    if self._cancelled:
                        self.progress.emit("Download cancelled by user.")
                        break
                    f_str = str(f)
                    all_downloaded.append(f_str)
                    self.file_downloaded.emit(f_str, i + 1, len(urls))
            else:
                # All-layers mode: download entire granule
                for i, granule in enumerate(self.granules):
                    if self._cancelled:
                        self.progress.emit("Download cancelled by user.")
                        break

                    granule_id = granule.get("meta", {}).get(
                        "native-id", f"Granule {i + 1}"
                    )
                    self.progress.emit(f"Downloading {i + 1}/{total}: {granule_id}...")

                    try:
                        downloaded = earthaccess.download(
                            [granule], local_path=self.download_dir, threads=1
                        )
                        for f in downloaded:
                            f_str = str(f)
                            all_downloaded.append(f_str)
                            self.file_downloaded.emit(f_str, i + 1, total)
                    except Exception as e:
                        self.progress.emit(
                            f"Warning: Failed to download {granule_id}: {str(e)}"
                        )

            self.finished.emit(all_downloaded)

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


class RectangleMapTool(QgsMapToolEmitPoint):
    """Map tool for drawing a rectangle on the canvas.

    Emits a rectangleCreated signal with the bounding box coordinates
    when the user finishes drawing.
    """

    rectangleCreated = pyqtSignal(QgsRectangle)

    def __init__(self, canvas):
        """Initialize the rectangle map tool.

        Args:
            canvas: The QgsMapCanvas to draw on.
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = None
        self.start_point = None
        self.end_point = None
        self.is_drawing = False

    def canvasPressEvent(self, event):
        """Handle mouse press to start drawing the rectangle.

        Args:
            event: The QgsMapMouseEvent.
        """
        self.start_point = self.toMapCoordinates(event.pos())
        self.end_point = self.start_point
        self.is_drawing = True

        # Create rubber band for visual feedback
        if self.rubber_band is not None:
            self.canvas.scene().removeItem(self.rubber_band)
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 100))
        self.rubber_band.setWidth(2)
        self._update_rubber_band()

    def canvasMoveEvent(self, event):
        """Handle mouse move to update the rectangle preview.

        Args:
            event: The QgsMapMouseEvent.
        """
        if not self.is_drawing:
            return
        self.end_point = self.toMapCoordinates(event.pos())
        self._update_rubber_band()

    def canvasReleaseEvent(self, event):
        """Handle mouse release to finalize the rectangle.

        Args:
            event: The QgsMapMouseEvent.
        """
        if not self.is_drawing:
            return
        self.end_point = self.toMapCoordinates(event.pos())
        self.is_drawing = False

        # Clean up rubber band
        if self.rubber_band is not None:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

        # Create rectangle from start and end points
        rect = QgsRectangle(self.start_point, self.end_point)
        rect.normalize()  # Ensure min < max

        if rect.width() > 0 and rect.height() > 0:
            self.rectangleCreated.emit(rect)

    def _update_rubber_band(self):
        """Update the rubber band rectangle display."""
        if self.rubber_band is None:
            return
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        rect = QgsRectangle(self.start_point, self.end_point)
        rect.normalize()
        self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
        self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
        self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
        self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), True)
        self.rubber_band.show()

    def deactivate(self):
        """Clean up when the tool is deactivated."""
        if self.rubber_band is not None:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None
        super().deactivate()


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

        # Rectangle drawing tool
        self._rectangle_tool = None
        self._previous_map_tool = None

        # Selection sync guard flag
        self._sync_in_progress = False

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
        header_label.setStyleSheet("color: #64B5F6; padding: 5px;")
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
        self.dataset_desc_label.setStyleSheet("color: #B0BEC5; font-size: 10px;")
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
        self.draw_rect_btn = QPushButton("Draw Rectangle")
        self.draw_rect_btn.clicked.connect(self._activate_draw_rectangle)
        self.clear_bbox_btn = QPushButton("Clear")
        self.clear_bbox_btn.clicked.connect(self._clear_bbox)
        bbox_btn_layout.addWidget(self.use_extent_btn)
        bbox_btn_layout.addWidget(self.draw_rect_btn)
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
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                font-weight: bold;
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
        """)
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
        self.status_label.setStyleSheet(
            "color: #B0BEC5; font-size: 10px; padding: 2px;"
        )
        layout.addWidget(self.status_label)

        # Results group
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        results_layout.setSpacing(4)

        # Granule table with multi-select
        granule_label = QLabel("Granules (select one or more):")
        results_layout.addWidget(granule_label)

        self.granule_table = QTableWidget()
        self.granule_table.setEnabled(False)
        self.granule_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.granule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.granule_table.setColumnCount(4)
        self.granule_table.setHorizontalHeaderLabels(
            ["Granule ID", "Begin Date", "End Date", "Links"]
        )
        self.granule_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.granule_table.horizontalHeader().setStretchLastSection(True)
        self.granule_table.setSortingEnabled(True)
        self.granule_table.setMinimumHeight(120)
        self.granule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.granule_table.itemSelectionChanged.connect(
            self._on_granule_selection_changed
        )
        results_layout.addWidget(self.granule_table)

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

        # Display buttons (Single + Mosaic)
        display_btn_layout = QHBoxLayout()

        self.display_single_btn = QPushButton("Display Single")
        self.display_single_btn.setEnabled(False)
        self.display_single_btn.clicked.connect(self._display_single)
        display_btn_layout.addWidget(self.display_single_btn)

        self.display_mosaic_btn = QPushButton("Display Mosaic")
        self.display_mosaic_btn.setEnabled(False)
        self.display_mosaic_btn.setToolTip(
            "Create a virtual mosaic from selected granules"
        )
        self.display_mosaic_btn.clicked.connect(self._display_mosaic)
        display_btn_layout.addWidget(self.display_mosaic_btn)

        results_layout.addLayout(display_btn_layout)

        # Download buttons
        download_btn_layout = QHBoxLayout()

        self.download_single_layer_btn = QPushButton("Download Selected (Single Layer)")
        self.download_single_layer_btn.setEnabled(False)
        self.download_single_layer_btn.setToolTip(
            "Download only the selected layer type for each granule"
        )
        self.download_single_layer_btn.clicked.connect(self._download_single_layer)
        download_btn_layout.addWidget(self.download_single_layer_btn)

        self.download_all_layers_btn = QPushButton("Download Selected (All Layers)")
        self.download_all_layers_btn.setEnabled(False)
        self.download_all_layers_btn.setToolTip(
            "Download all layer files for each selected granule"
        )
        self.download_all_layers_btn.clicked.connect(self._download_all_layers)
        download_btn_layout.addWidget(self.download_all_layers_btn)

        results_layout.addLayout(download_btn_layout)

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

    def _activate_draw_rectangle(self):
        """Activate the rectangle drawing tool on the map canvas."""
        canvas = self.iface.mapCanvas()

        # Save the current map tool to restore later
        self._previous_map_tool = canvas.mapTool()

        # Create the rectangle tool if it doesn't exist
        if self._rectangle_tool is None:
            self._rectangle_tool = RectangleMapTool(canvas)
            self._rectangle_tool.rectangleCreated.connect(self._on_rectangle_drawn)

        canvas.setMapTool(self._rectangle_tool)
        self.status_label.setText("Draw a rectangle on the map...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")

    def _on_rectangle_drawn(self, rect):
        """Handle completion of rectangle drawing.

        Args:
            rect: QgsRectangle with the drawn extent.
        """
        canvas = self.iface.mapCanvas()

        # Transform to WGS84
        source_crs = canvas.mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if source_crs != dest_crs:
            transform = QgsCoordinateTransform(
                source_crs, dest_crs, QgsProject.instance()
            )
            rect = transform.transformBoundingBox(rect)

        bbox_str = (
            f"{rect.xMinimum():.6f}, {rect.yMinimum():.6f}, "
            f"{rect.xMaximum():.6f}, {rect.yMaximum():.6f}"
        )
        self.bbox_input.setText(bbox_str)

        self.status_label.setText("Rectangle drawn - bbox set")
        self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")

        # Restore previous map tool
        if self._previous_map_tool is not None:
            canvas.setMapTool(self._previous_map_tool)
        else:
            canvas.unsetMapTool(self._rectangle_tool)

    def _clear_bbox(self):
        """Clear the bounding box input and remove footprint layer."""
        self.bbox_input.clear()
        self._remove_footprint_layer()

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
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(True)
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
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
            self.status_label.setStyleSheet("color: #FFA726; font-size: 10px;")
            self.output_text.append("No granules found matching the search criteria.")
            return

        self.status_label.setText(f"Found {len(results)} granules")
        self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
        self.output_text.append(f"\nFound {len(results)} granules.")
        self.output_text.append("Select granule(s) from the list to display.")

        # Populate granule table
        self.granule_table.setSortingEnabled(False)  # Disable during population
        self.granule_table.setRowCount(0)
        self.granule_table.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)

        for i, result in enumerate(results):
            row = self.granule_table.rowCount()
            self.granule_table.insertRow(row)

            native_id = result.get("meta", {}).get("native-id", f"Granule {i + 1}")
            id_item = QTableWidgetItem(native_id)
            id_item.setData(Qt.UserRole, i)  # Store granule index
            id_item.setToolTip(native_id)
            self.granule_table.setItem(row, 0, id_item)

            # Get temporal info and links from GeoDataFrame if available
            begin_date = ""
            end_date = ""
            num_links = 0
            if gdf is not None:
                row_gdf = None
                try:
                    row_gdf = gdf.iloc[i]
                except IndexError:
                    pass
                if row_gdf is not None:
                    begin_date = str(row_gdf.get("begin_date", ""))[:10]
                    end_date = str(row_gdf.get("end_date", ""))[:10]
                    try:
                        num_links = int(row_gdf.get("num_links", 0))
                    except (TypeError, ValueError):
                        num_links = 0

            self.granule_table.setItem(row, 1, QTableWidgetItem(begin_date))
            self.granule_table.setItem(row, 2, QTableWidgetItem(end_date))

            links_item = QTableWidgetItem()
            links_item.setData(Qt.DisplayRole, num_links)  # Numeric sort
            self.granule_table.setItem(row, 3, links_item)

        self.granule_table.setSortingEnabled(True)  # Re-enable sorting
        self.granule_table.resizeColumnsToContents()

        # Select first row by default
        if self.granule_table.rowCount() > 0:
            self.granule_table.selectRow(0)

        # Auto-show footprints
        if gdf is not None:
            self._display_footprints()

    def _on_search_error(self, error_msg):
        """Handle search error."""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        self.status_label.setText("Search failed")
        self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
        self.output_text.append(f"\nError: {error_msg}")

        QMessageBox.critical(self, "Search Error", f"Failed to search:\n{error_msg}")

    def _on_granule_selection_changed(self):
        """Handle granule selection change in the table widget."""
        if self._sync_in_progress:
            return

        selected_rows = set()
        for item in self.granule_table.selectedItems():
            selected_rows.add(item.row())
        num_selected = len(selected_rows)

        # Enable/disable buttons based on selection
        self.display_single_btn.setEnabled(num_selected == 1)
        self.display_mosaic_btn.setEnabled(num_selected >= 1)
        self.download_single_layer_btn.setEnabled(num_selected >= 1)
        self.download_all_layers_btn.setEnabled(num_selected >= 1)

        if num_selected == 0:
            self.layer_combo.clear()
            self.layer_combo.setEnabled(False)
            # Clear map selection
            if self._footprint_layer is not None:
                self._sync_in_progress = True
                self._footprint_layer.removeSelection()
                self._sync_in_progress = False
            return

        # Get the first selected granule to populate layer dropdown
        first_row = min(selected_rows)
        item = self.granule_table.item(first_row, 0)
        if item is None:
            return
        index = item.data(Qt.UserRole)

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

        # Sync selection to footprint layer on map
        self._sync_table_to_map(selected_rows)

    def _sync_table_to_map(self, selected_rows):
        """Highlight footprints on the map corresponding to selected table rows.

        Args:
            selected_rows: Set of selected row indices in the table.
        """
        if self._footprint_layer is None:
            return
        if self._sync_in_progress:
            return

        self._sync_in_progress = True
        try:
            # Map table rows to granule indices, then to feature IDs
            feature_ids = []
            for row in selected_rows:
                item = self.granule_table.item(row, 0)
                if item is not None:
                    granule_index = item.data(Qt.UserRole)
                    if granule_index is not None:
                        feature_ids.append(granule_index)

            try:
                self._footprint_layer.selectByIds(feature_ids)
            except Exception:
                self._footprint_layer = None
        finally:
            self._sync_in_progress = False

    def _on_footprint_selection_changed(self, selected, deselected, clear_and_select):
        """Handle selection changes on the footprint layer to sync to table.

        Args:
            selected: List of newly selected feature IDs.
            deselected: List of newly deselected feature IDs.
            clear_and_select: Whether this was a clear-and-select operation.
        """
        if self._sync_in_progress:
            return

        self._sync_in_progress = True
        try:
            # Get selected feature IDs from the layer
            selected_fids = self._footprint_layer.selectedFeatureIds()

            # Build a mapping from granule_index to table row
            index_to_row = {}
            for row in range(self.granule_table.rowCount()):
                item = self.granule_table.item(row, 0)
                if item is not None:
                    granule_index = item.data(Qt.UserRole)
                    if granule_index is not None:
                        index_to_row[granule_index] = row

            # Select matching rows in the table
            self.granule_table.clearSelection()
            for fid in selected_fids:
                if fid in index_to_row:
                    row = index_to_row[fid]
                    for col in range(self.granule_table.columnCount()):
                        item = self.granule_table.item(row, col)
                        if item is not None:
                            item.setSelected(True)
        finally:
            self._sync_in_progress = False

    def _select_all_granules(self):
        """Select all granules in the table."""
        self.granule_table.selectAll()

    def _deselect_all_granules(self):
        """Deselect all granules in the table."""
        self.granule_table.clearSelection()

    def _display_single(self):
        """Display selected granule layer."""
        if self.layer_combo.count() == 0:
            return

        url = self.layer_combo.currentData()
        if not url:
            QMessageBox.warning(self, "Error", "No valid layer selected")
            return

        # Get the selected granule from the table
        selected_rows = set()
        for item in self.granule_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            QMessageBox.warning(self, "Error", "No granule selected")
            return

        first_row = min(selected_rows)
        granule_index = self.granule_table.item(first_row, 0).data(Qt.UserRole)
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
            self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
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
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
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
            self.display_mosaic_btn.setEnabled(False)
            self.download_single_layer_btn.setEnabled(False)
            self.download_all_layers_btn.setEnabled(False)
        else:
            QApplication.restoreOverrideCursor()
            # Re-enable buttons based on selection state
            selected_rows = set()
            for item in self.granule_table.selectedItems():
                selected_rows.add(item.row())
            num_selected = len(selected_rows)
            self.display_single_btn.setEnabled(num_selected == 1)
            self.display_mosaic_btn.setEnabled(num_selected >= 1)
            self.download_single_layer_btn.setEnabled(num_selected >= 1)
            self.download_all_layers_btn.setEnabled(num_selected >= 1)

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
                self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
                self.output_text.append("Successfully loaded COG via cloud streaming!")
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
                self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
                self.output_text.append(f"Successfully loaded layer: {layer_name}")
                self.output_text.append(f"File: {file_path}")
            else:
                raise Exception(f"Layer is not valid: {file_path}")

        except Exception as e:
            self.status_label.setText("Failed to load layer")
            self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
            self.output_text.append(f"Error loading layer: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load layer:\n{str(e)}")

    def _on_download_error(self, error_msg):
        """Handle download error."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        self.status_label.setText("Download failed")
        self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
        self.output_text.append(f"Error: {error_msg}")

        QMessageBox.critical(
            self, "Download Error", f"Failed to download:\n{error_msg}"
        )

    def _display_mosaic(self):
        """Display a virtual mosaic from selected granules.

        Creates separate mosaics for each projection/UTM zone to ensure proper alignment.
        Uses a determinate progress bar that updates after each file is verified.
        """
        selected_rows = set()
        for item in self.granule_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            QMessageBox.warning(self, "Error", "No granules selected")
            return

        # Get the selected layer type - extract just the layer suffix (e.g., B01_WTR.tif)
        layer_filename = self.layer_combo.currentText()
        if not layer_filename or layer_filename == "No raster files available":
            QMessageBox.warning(self, "Error", "No layer type selected")
            return

        # Extract the layer band identifier from the filename
        import re

        match = re.search(r"_(B\d+_[A-Za-z0-9]+)\.tif$", layer_filename, re.IGNORECASE)
        if match:
            layer_band = match.group(1)
        else:
            match = re.search(r"_([VH]{2})\.tif$", layer_filename, re.IGNORECASE)
            if match:
                layer_band = match.group(1)
            else:
                parts = layer_filename.replace(".tif", "").split("_")
                layer_band = parts[-1] if parts else layer_filename

        num_selected = len(selected_rows)

        # Show busy state with determinate progress bar
        self._set_busy_state(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, num_selected)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Creating mosaic from {num_selected} granules...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
        self.output_text.append(f"\nCreating mosaic from {num_selected} granules...")
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
            files_by_crs = {}
            not_found = []
            access_failed = []

            total_granules = num_selected
            for idx, row in enumerate(sorted(selected_rows)):
                granule_index = self.granule_table.item(row, 0).data(Qt.UserRole)
                if granule_index is None or granule_index >= len(self._results):
                    self.progress_bar.setValue(idx + 1)
                    continue

                granule = self._results[granule_index]
                granule_id = self.granule_table.item(row, 0).text()
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
                    if (
                        f"_{layer_band}.tif".lower() in link.lower()
                        or link.lower().endswith(f"_{layer_band}.tif".lower())
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

                                crs_name = (
                                    srs.GetName() if srs.GetName() else "Unknown CRS"
                                )
                                zone_match = re.search(
                                    r"(UTM zone \d+[NS]?)",
                                    crs_name,
                                    re.IGNORECASE,
                                )
                                if zone_match:
                                    crs_short = zone_match.group(1)
                                else:
                                    crs_short = crs_name[:30]

                                epsg = srs.GetAuthorityCode(None)
                                if epsg:
                                    crs_key = f"EPSG:{epsg}"
                                else:
                                    crs_key = proj[:100]

                                if crs_key not in files_by_crs:
                                    files_by_crs[crs_key] = {
                                        "name": crs_short,
                                        "paths": [],
                                        "nodata": None,
                                    }
                                files_by_crs[crs_key]["paths"].append(vsi_path)

                                if files_by_crs[crs_key]["nodata"] is None:
                                    band = ds.GetRasterBand(1)
                                    files_by_crs[crs_key][
                                        "nodata"
                                    ] = band.GetNoDataValue()

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

                self.progress_bar.setValue(idx + 1)
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

                # Use nodata value detected from source files
                group_nodata = crs_data.get("nodata")
                if (
                    group_nodata is not None
                    and isinstance(group_nodata, float)
                    and math.isnan(group_nodata)
                ):
                    nodata_display = "NaN"
                    vrt_options = gdal.BuildVRTOptions(
                        resampleAlg="nearest",
                        addAlpha=False,
                        srcNodata="nan",
                        VRTNodata="nan",
                    )
                elif group_nodata is not None:
                    nodata_display = str(group_nodata)
                    vrt_options = gdal.BuildVRTOptions(
                        resampleAlg="nearest",
                        addAlpha=False,
                        srcNodata=group_nodata,
                        VRTNodata=group_nodata,
                    )
                else:
                    nodata_display = "auto (from source metadata)"
                    vrt_options = gdal.BuildVRTOptions(
                        resampleAlg="nearest",
                        addAlpha=False,
                    )
                self.output_text.append(f"  Nodata value: {nodata_display}")

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
            self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
            self.output_text.append(
                f"\nSuccessfully created {len(layers_created)} mosaic layer(s) "
                f"with {total_files} scenes total!"
            )

        except Exception as e:
            self.status_label.setText("Mosaic failed")
            self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
            self.output_text.append(f"\nError creating mosaic: {str(e)}")
            QMessageBox.critical(
                self, "Mosaic Error", f"Failed to create mosaic:\n{str(e)}"
            )

        finally:
            self._set_busy_state(False)
            self.progress_bar.setVisible(False)

    def _remove_footprint_layer(self):
        """Remove the footprint layer from the map if it exists."""
        if self._footprint_layer is not None:
            try:
                layer_id = self._footprint_layer.id()
                if layer_id in QgsProject.instance().mapLayers():
                    QgsProject.instance().removeMapLayer(layer_id)
            except RuntimeError:
                pass  # Underlying C++ object already deleted
            self._footprint_layer = None

        # Also remove any orphaned footprint layers by name
        for lyr in list(QgsProject.instance().mapLayers().values()):
            if lyr.name().startswith("OPERA Footprints"):
                QgsProject.instance().removeMapLayer(lyr.id())

        self.iface.mapCanvas().refresh()

    def _display_footprints(self):
        """Display search result footprints as a vector layer."""
        if self._gdf is None:
            QMessageBox.warning(self, "Error", "No footprint data available")
            return

        try:
            # Remove existing footprint layer
            self._remove_footprint_layer()

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

                # Connect selection sync from map to table
                self._footprint_layer.selectionChanged.connect(
                    self._on_footprint_selection_changed
                )

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
                self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
                self.output_text.append(f"Displayed {len(self._gdf)} footprints on map")
            else:
                raise Exception("Failed to create footprint layer")

        except Exception as e:
            self.status_label.setText("Failed to display footprints")
            self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
            self.output_text.append(f"Error: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to display footprints:\n{str(e)}"
            )

    def _get_selected_granules(self):
        """Get granule objects for all selected table rows.

        Returns:
            List of granule objects, or empty list if none selected.
        """
        selected_rows = set()
        for item in self.granule_table.selectedItems():
            selected_rows.add(item.row())

        granules = []
        for row in sorted(selected_rows):
            index = self.granule_table.item(row, 0).data(Qt.UserRole)
            if index is not None and index < len(self._results):
                granules.append(self._results[index])
        return granules

    def _get_layer_band(self):
        """Extract the layer band identifier from the selected layer filename.

        Returns:
            The band identifier string (e.g. "B01_WTR", "VV"), or None.
        """
        import re

        layer_filename = self.layer_combo.currentText()
        if not layer_filename or layer_filename == "No raster files available":
            return None

        match = re.search(r"_(B\d+_[A-Za-z0-9]+)\.tif$", layer_filename, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"_([VH]{2})\.tif$", layer_filename, re.IGNORECASE)
        if match:
            return match.group(1)
        parts = layer_filename.replace(".tif", "").split("_")
        return parts[-1] if parts else layer_filename

    def _start_download(self, granules, download_dir, layer_filter=None):
        """Start the download worker for the given granules.

        Args:
            granules: List of granule objects to download.
            download_dir: Directory path to save downloaded files.
            layer_filter: Optional layer band suffix to filter downloads.
        """
        mode = f" ({layer_filter} only)" if layer_filter else " (all layers)"
        self._set_busy_state(True)
        self.progress_bar.setVisible(True)
        if layer_filter:
            # Single-layer mode: actual file count may differ from granule count
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, len(granules))
            self.progress_bar.setValue(0)
        self.status_label.setText(f"Downloading {len(granules)} granules{mode}...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
        self.output_text.append(
            f"\nStarting download of {len(granules)} granules{mode} to:"
        )
        self.output_text.append(f"  {download_dir}")

        self._download_granules_worker = DownloadGranulesWorker(
            granules=granules,
            download_dir=download_dir,
            layer_filter=layer_filter,
        )
        self._download_granules_worker.progress.connect(self._on_bulk_download_progress)
        self._download_granules_worker.file_downloaded.connect(self._on_file_downloaded)
        self._download_granules_worker.finished.connect(self._on_bulk_download_finished)
        self._download_granules_worker.error.connect(self._on_bulk_download_error)
        self._download_granules_worker.start()

    def _download_single_layer(self):
        """Download only the selected layer type for each selected granule."""
        granules = self._get_selected_granules()
        if not granules:
            QMessageBox.warning(self, "Error", "No granules selected")
            return

        layer_band = self._get_layer_band()
        if not layer_band:
            QMessageBox.warning(self, "Error", "No layer type selected")
            return

        default_dir = self.settings.value("NasaOpera/cache_dir", "")
        if not default_dir:
            default_dir = os.path.join(os.path.expanduser("~"), "opera_downloads")

        download_dir = QFileDialog.getExistingDirectory(
            self, "Select Download Directory", default_dir
        )
        if not download_dir:
            return

        self._start_download(granules, download_dir, layer_filter=layer_band)

    def _download_all_layers(self):
        """Download all layer files for each selected granule."""
        granules = self._get_selected_granules()
        if not granules:
            QMessageBox.warning(self, "Error", "No granules selected")
            return

        default_dir = self.settings.value("NasaOpera/cache_dir", "")
        if not default_dir:
            default_dir = os.path.join(os.path.expanduser("~"), "opera_downloads")

        download_dir = QFileDialog.getExistingDirectory(
            self, "Select Download Directory", default_dir
        )
        if not download_dir:
            return

        self._start_download(granules, download_dir)

    def _on_bulk_download_progress(self, message):
        """Handle bulk download progress update.

        Args:
            message: Progress message string.
        """
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_file_downloaded(self, file_path, current, total):
        """Handle individual file download completion.

        Args:
            file_path: Path to the downloaded file.
            current: Current file number (1-based).
            total: Total number of files.
        """
        self.progress_bar.setValue(current)
        self.output_text.append(f"  Downloaded: {os.path.basename(file_path)}")

    def _on_bulk_download_finished(self, downloaded_files):
        """Handle bulk download completion.

        Args:
            downloaded_files: List of paths to downloaded files.
        """
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        count = len(downloaded_files)
        self.status_label.setText(f"Downloaded {count} files")
        self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
        self.output_text.append(f"\nDownload complete: {count} files downloaded.")

    def _on_bulk_download_error(self, error_msg):
        """Handle bulk download error.

        Args:
            error_msg: Error message string.
        """
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        self.status_label.setText("Download failed")
        self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
        self.output_text.append(f"\nDownload error: {error_msg}")
        QMessageBox.critical(
            self, "Download Error", f"Failed to download:\n{error_msg}"
        )

    def _reset(self):
        """Reset the search interface."""
        self.bbox_input.clear()
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.end_date_edit.setDate(QDate.currentDate())
        self.max_items_spin.setValue(50)
        self.dataset_combo.setCurrentIndex(0)

        self.granule_table.setRowCount(0)
        self.granule_table.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.deselect_all_btn.setEnabled(False)
        self.layer_combo.clear()
        self.layer_combo.setEnabled(False)

        self.display_single_btn.setEnabled(False)
        self.display_mosaic_btn.setEnabled(False)
        self.download_single_layer_btn.setEnabled(False)
        self.download_all_layers_btn.setEnabled(False)

        self.output_text.clear()
        self.status_label.setText("Ready to search")
        self.status_label.setStyleSheet("color: #B0BEC5; font-size: 10px;")

        # Remove footprint layer from map
        self._remove_footprint_layer()

        self._results = []
        self._gdf = None

    def closeEvent(self, event):
        """Handle dock widget close event."""
        # Deactivate rectangle tool if active
        if self._rectangle_tool is not None:
            self.iface.mapCanvas().unsetMapTool(self._rectangle_tool)
            self._rectangle_tool = None

        # Clean up any running worker threads
        for attr_name in ("_download_granules_worker", "_search_worker"):
            worker = getattr(self, attr_name, None)
            if worker is not None:
                if hasattr(worker, "cancel"):
                    try:
                        worker.cancel()
                    except Exception:
                        pass
                if hasattr(worker, "wait"):
                    try:
                        worker.wait()
                    except Exception:
                        pass

        event.accept()
