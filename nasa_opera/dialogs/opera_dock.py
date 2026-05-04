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
import sys
import tempfile
import hashlib
from datetime import datetime, date
from urllib.parse import urlparse
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
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QAbstractItemView,
    QFileDialog,
)
from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsRasterRange,
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


HDF5_EXTENSIONS = (".h5", ".hdf5", ".hdf")
RASTER_EXTENSIONS = (".tif", ".tiff") + HDF5_EXTENSIONS


def _filename_from_url(url: str) -> str:
    """Return a clean filename from a local path or URL."""
    parsed = urlparse(url)
    path = parsed.path if parsed.path else url
    return os.path.basename(path)


def _is_hdf5_path(path: str) -> bool:
    """Return True when a source path points to an HDF5 container."""
    return _filename_from_url(path).lower().endswith(HDF5_EXTENSIONS)


def _link_matches_layer_filter(link: str, layer_filter: str) -> bool:
    """Match a granule link against a selected layer or filename filter."""
    filename = _filename_from_url(link).lower()
    layer_filter = layer_filter.lower()

    if layer_filter.endswith(RASTER_EXTENSIONS):
        return filename == layer_filter or filename.endswith(layer_filter)

    return (
        f"_{layer_filter}.tif" in filename
        or filename.endswith(f"_{layer_filter}.tif")
        or f"_{layer_filter}.tiff" in filename
        or filename.endswith(f"_{layer_filter}.tiff")
    )


def _is_metadata_subdataset(name: str, description: str) -> bool:
    """Return True for HDF5 subdatasets that should not be displayed as rasters."""
    text = f"{name} {description}".lower()
    metadata_paths = (
        "://metadata/",
        "://identification/",
        "/metadata/",
        "/identification/",
        "/orbit/",
        "/processinginformation/",
        "/sourcedata/",
        "/qa/",
    )
    return any(path in text for path in metadata_paths)


def _subdataset_layer_name(base_layer_name: str, source: str, description: str) -> str:
    """Build a readable QGIS layer name for an HDF5 subdataset."""
    label = description
    if "://" in source:
        label = source.split("://", 1)[1]
    if "]" in label:
        label = label.split("]", 1)[-1].strip()
    label = label.strip().strip("/")
    if label:
        label = label.replace("/", " - ")
        return f"{base_layer_name} - {label}"
    return base_layer_name


def _parse_hdf5_subdataset_source(source: str):
    """Return (file_path, dataset_path) for a GDAL HDF5 subdataset source."""
    prefix = 'HDF5:"'
    marker = '"://'
    if not source.startswith(prefix):
        return None

    rest = source[len(prefix) :]
    marker_index = rest.find(marker)
    if marker_index < 0:
        return None

    file_path = rest[:marker_index]
    dataset_path = rest[marker_index + len(marker) :]
    if not file_path or not dataset_path:
        return None
    return file_path, dataset_path


def _decode_hdf5_value(value):
    """Convert HDF5 byte/scalar values to plain Python values."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _first_hdf5_dataset(group, names):
    """Return the first matching dataset from an HDF5 group."""
    for name in names:
        if name in group:
            return group[name]
    return None


def _georef_from_coordinate_values(x_values, y_values, width, height, spatial_ref):
    """Build GDAL georeferencing arguments from center coordinate arrays."""
    if len(x_values) != width or len(y_values) != height or not spatial_ref:
        return None

    x_res = float(x_values[1] - x_values[0]) if len(x_values) > 1 else 1.0
    y_res = float(y_values[1] - y_values[0]) if len(y_values) > 1 else -1.0

    upper_left_x = float(x_values[0]) - x_res / 2.0
    upper_left_y = float(y_values[0]) - y_res / 2.0
    lower_right_x = upper_left_x + x_res * width
    lower_right_y = upper_left_y + y_res * height

    return {
        "output_srs": spatial_ref,
        "output_bounds": [
            upper_left_x,
            upper_left_y,
            lower_right_x,
            lower_right_y,
        ],
    }


def _read_hdf5_coordinate_values_with_gdal(file_path, dataset_path):
    """Read a one-dimensional OPERA HDF5 coordinate dataset through GDAL."""
    from osgeo import gdal

    source = f'HDF5:"{file_path}"://{dataset_path}'
    try:
        dataset = gdal.Open(source)
    except Exception:
        dataset = None
    if dataset is None:
        return None

    values = dataset.ReadAsArray()
    dataset = None
    if values is None:
        return None
    return values.flatten()


def _hdf5_subdataset_georef_from_gdal(file_path, group_path, width, height):
    """Read OPERA HDF5 georeferencing through GDAL metadata and coordinate arrays."""
    from osgeo import gdal

    x_values = None
    y_values = None
    for name in ("x_coordinates", "xCoordinates"):
        x_values = _read_hdf5_coordinate_values_with_gdal(
            file_path, f"{group_path}/{name}"
        )
        if x_values is not None:
            break
    for name in ("y_coordinates", "yCoordinates"):
        y_values = _read_hdf5_coordinate_values_with_gdal(
            file_path, f"{group_path}/{name}"
        )
        if y_values is not None:
            break
    if x_values is None or y_values is None:
        return None

    try:
        container = gdal.Open(file_path)
    except Exception:
        container = None
    if container is None:
        return None

    metadata = container.GetMetadata()
    container = None
    metadata_prefix = group_path.replace("/", "_")
    spatial_ref = metadata.get(f"{metadata_prefix}_projection_spatial_ref")
    if not spatial_ref:
        epsg = metadata.get(f"{metadata_prefix}_projection_epsg_code")
        if epsg:
            spatial_ref = f"EPSG:{int(float(epsg))}"

    return _georef_from_coordinate_values(
        x_values, y_values, width, height, spatial_ref
    )


def _hdf5_subdataset_georef(source: str, width: int, height: int):
    """Read OPERA HDF5 coordinate arrays and return GDAL Translate georef args."""
    parsed = _parse_hdf5_subdataset_source(source)
    if parsed is None:
        return None

    file_path, dataset_path = parsed
    group_path = dataset_path.rsplit("/", 1)[0] if "/" in dataset_path else ""
    if not group_path:
        return None

    georef = _hdf5_subdataset_georef_from_gdal(file_path, group_path, width, height)
    if georef is not None:
        return georef

    if file_path.startswith("/vsi"):
        return None

    try:
        import h5py
    except Exception:
        return None

    try:
        with h5py.File(file_path, "r") as hdf:
            if group_path not in hdf:
                return None

            group = hdf[group_path]
            x_dataset = _first_hdf5_dataset(group, ("x_coordinates", "xCoordinates"))
            y_dataset = _first_hdf5_dataset(group, ("y_coordinates", "yCoordinates"))
            projection_dataset = _first_hdf5_dataset(group, ("projection",))
            if x_dataset is None or y_dataset is None or projection_dataset is None:
                return None

            x_values = x_dataset[()]
            y_values = y_dataset[()]
            spatial_ref = _decode_hdf5_value(
                projection_dataset.attrs.get("spatial_ref", "")
            )
            if not spatial_ref:
                epsg = projection_dataset.attrs.get("epsg_code")
                if epsg is None:
                    epsg = projection_dataset[()]
                epsg = _decode_hdf5_value(epsg)
                spatial_ref = f"EPSG:{int(epsg)}"

            return _georef_from_coordinate_values(
                x_values, y_values, width, height, spatial_ref
            )
    except Exception:
        return None


def _georeferenced_hdf5_vrt(source: str, width: int, height: int):
    """Create a georeferenced VRT wrapper for an HDF5 raster subdataset."""
    georef = _hdf5_subdataset_georef(source, width, height)
    if georef is None:
        return source

    from osgeo import gdal

    # SHA1 here is only a deterministic filename digest, not a security primitive.
    digest = hashlib.sha1(source.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :16
    ]
    vrt_path = os.path.join(tempfile.gettempdir(), f"opera_hdf5_{digest}.vrt")
    options = gdal.TranslateOptions(
        format="VRT",
        outputSRS=georef["output_srs"],
        outputBounds=georef["output_bounds"],
    )
    vrt_dataset = gdal.Translate(vrt_path, source, options=options)
    if vrt_dataset is None:
        return source

    vrt_dataset.FlushCache()
    vrt_dataset = None
    return vrt_path


def _displayable_gdal_sources(path: str, layer_name: str):
    """Return GDAL raster sources inside a file, expanding HDF5 subdatasets."""
    from osgeo import gdal

    gdal.UseExceptions()

    try:
        dataset = gdal.Open(path)
    except Exception:
        dataset = None

    if dataset is None:
        return []

    if dataset.RasterCount > 0:
        dataset = None
        return [(path, layer_name)]

    subdatasets = dataset.GetSubDatasets()
    dataset = None
    displayable = []

    for source, description in subdatasets:
        if _is_metadata_subdataset(source, description):
            continue

        try:
            subdataset = gdal.Open(source)
        except Exception:
            subdataset = None
        if subdataset is None:
            continue

        has_raster = (
            subdataset.RasterCount > 0
            and subdataset.RasterXSize > 1
            and subdataset.RasterYSize > 1
        )
        width = subdataset.RasterXSize
        height = subdataset.RasterYSize
        subdataset = None
        if not has_raster:
            continue

        display_source = _georeferenced_hdf5_vrt(source, width, height)
        displayable.append(
            (display_source, _subdataset_layer_name(layer_name, source, description))
        )

    return displayable


def _earthdata_login():
    """Authenticate with NASA Earthdata using non-interactive strategies.

    Raises:
        RuntimeError: If authentication fails (credentials not configured).
    """
    import earthaccess

    auth = None
    for strategy in ("environment", "netrc"):
        try:
            auth = earthaccess.login(strategy=strategy)
            if auth:
                return
        except Exception as exc:
            print(
                f"NASA OPERA: earthaccess login via {strategy} failed: {exc}",
                file=sys.stderr,
            )
            continue

    raise RuntimeError(
        "NASA Earthdata authentication failed.\n\n"
        "Please open the Settings tab (Plugins > NASA OPERA > Settings > "
        "Credentials) and enter your Earthdata username and password."
    )


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
            _earthdata_login()

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
                # Don't set crs= here to avoid pyproj/PROJ database issues
                # in the isolated venv. GeoJSON is WGS84 by spec, and QGIS
                # assigns CRS when loading the layer.
                gdf = gpd.GeoDataFrame(df, geometry="geometry")

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
            _earthdata_login()

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
                    f_str = str(f)
                    if _filename_from_url(f_str) == filename:
                        self.finished.emit(f_str, self.layer_name)
                        return

                # If we couldn't find the exact file, try to find any matching raster
                for f in downloaded_files:
                    f_str = str(f) if not isinstance(f, str) else f
                    if _filename_from_url(f_str).lower().endswith(RASTER_EXTENSIONS):
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


class CogStreamWorker(QThread):
    """Worker thread for preparing a cloud-streamed COG layer."""

    ready = pyqtSignal(bool, str, str, str)  # success, vsi_path, layer_name, error
    progress = pyqtSignal(str)

    def __init__(self, url: str, layer_name: str):
        super().__init__()
        self.url = url
        self.layer_name = layer_name

    def run(self):
        """Prepare and validate the COG path without blocking the QGIS UI."""
        try:
            from osgeo import gdal

            self.progress.emit("Setting up cloud access...")
            success, error = setup_gdal_for_earthdata()
            if not success:
                self.ready.emit(False, "", self.layer_name, error or "")
                return

            vsi_path = get_vsicurl_path(self.url)
            self.progress.emit(f"Trying: {vsi_path}")
            self.progress.emit(f"Checking COG: {self.layer_name}...")

            ds = gdal.Open(vsi_path)
            if ds is None:
                self.ready.emit(
                    False, "", self.layer_name, "Layer not valid via cloud access"
                )
                return

            ds = None
            self.ready.emit(True, vsi_path, self.layer_name, "")
        except Exception as e:
            self.ready.emit(False, "", self.layer_name, str(e))


class MosaicBuildWorker(QThread):
    """Worker thread for verifying COGs and building OPERA mosaic VRTs."""

    ready = pyqtSignal(object)  # dict with VRT layer metadata
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)

    def __init__(self, selected_granules, layer_band: str):
        super().__init__()
        self.selected_granules = selected_granules
        self.layer_band = layer_band

    def run(self):
        """Verify selected raster files and build VRT mosaics."""
        try:
            import re
            from osgeo import gdal, osr

            total_granules = len(self.selected_granules)
            self.progress.emit("Setting up cloud access...")
            success, error = setup_gdal_for_earthdata()
            if not success:
                raise RuntimeError(f"Failed to setup cloud access: {error}")

            gdal.UseExceptions()

            files_by_crs = {}
            not_found = []
            access_failed = []

            for idx, granule_info in enumerate(self.selected_granules):
                granule_id = granule_info["granule_id"]
                data_links = granule_info["data_links"]

                self.progress.emit(f"Checking file {idx + 1}/{total_granules}...")

                found = False
                for link in data_links:
                    if _link_matches_layer_filter(link, self.layer_band):
                        vsi_path = get_vsicurl_path(link)

                        try:
                            displayable_paths = _displayable_gdal_sources(
                                vsi_path, self.layer_band
                            )
                            if displayable_paths:
                                raster_path = displayable_paths[0][0]
                                ds = gdal.Open(raster_path)
                                if ds is None:
                                    raise RuntimeError("cannot open raster subdataset")
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
                                files_by_crs[crs_key]["paths"].append(raster_path)

                                if files_by_crs[crs_key]["nodata"] is None:
                                    band = ds.GetRasterBand(1)
                                    files_by_crs[crs_key][
                                        "nodata"
                                    ] = band.GetNoDataValue()

                                self.progress.emit(
                                    f"  [{idx + 1}] OK: {_filename_from_url(link)} "
                                    f"({crs_short})"
                                )
                                ds = None
                                found = True
                            else:
                                access_failed.append(_filename_from_url(link))
                                self.progress.emit(
                                    f"  [{idx + 1}] FAILED: {_filename_from_url(link)} "
                                    "(no displayable raster bands)"
                                )
                        except Exception as e:
                            access_failed.append(_filename_from_url(link))
                            self.progress.emit(
                                f"  [{idx + 1}] FAILED: {_filename_from_url(link)} "
                                f"({str(e)[:50]})"
                            )
                        break

                if not found and granule_id not in [
                    f[:30] + "..." for f in access_failed
                ]:
                    not_found.append(granule_id[:40])
                    self.progress.emit(
                        f"  [{idx + 1}] NOT FOUND: No {self.layer_band} in granule"
                    )

                self.progress_value.emit(idx + 1)

            total_files = sum(len(v["paths"]) for v in files_by_crs.values())
            if total_files == 0:
                raise RuntimeError("No accessible files found for selected granules")

            if not_found:
                self.progress.emit(
                    f"\nWarning: {len(not_found)} granules missing layer "
                    f"{self.layer_band}"
                )
            if access_failed:
                self.progress.emit(
                    f"Warning: {len(access_failed)} files failed to open"
                )

            self.progress.emit(
                f"\nSuccessfully verified {total_files} of {total_granules} files"
            )
            self.progress.emit(f"Found {len(files_by_crs)} different projection(s)")

            temp_dir = tempfile.gettempdir()
            vrt_layers = []

            for crs_idx, (_crs_key, crs_data) in enumerate(files_by_crs.items()):
                crs_name = crs_data["name"]
                vsi_paths = crs_data["paths"]

                self.progress.emit(
                    f"\nBuilding mosaic for {crs_name} ({len(vsi_paths)} files)..."
                )

                vrt_filename = (
                    f"opera_mosaic_{crs_name.replace(' ', '_').replace('/', '_')}.vrt"
                )
                vrt_path = os.path.join(temp_dir, vrt_filename)

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
                self.progress.emit(f"  Nodata value: {nodata_display}")

                vrt_ds = gdal.BuildVRT(vrt_path, vsi_paths, options=vrt_options)
                if vrt_ds is None:
                    gdal_error = gdal.GetLastErrorMsg()
                    self.progress.emit(
                        f"  Warning: Failed to build VRT for {crs_name}: "
                        f"{gdal_error}"
                    )
                    continue

                vrt_width = vrt_ds.RasterXSize
                vrt_height = vrt_ds.RasterYSize
                vrt_ds.FlushCache()
                vrt_ds = None

                self.progress.emit(f"  VRT created: {vrt_width}x{vrt_height} pixels")
                layer_name = f"OPERA Mosaic - {crs_name} ({len(vsi_paths)} scenes)"
                vrt_layers.append(
                    {
                        "path": vrt_path,
                        "layer_name": layer_name,
                        "crs_name": crs_name,
                        "file_count": len(vsi_paths),
                    }
                )
                self.progress_value.emit(total_granules + crs_idx + 1)

            if not vrt_layers:
                raise RuntimeError("Failed to create any mosaic layers")

            self.ready.emit(
                {
                    "layers": vrt_layers,
                    "total_files": total_files,
                    "total_granules": total_granules,
                }
            )
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
            _earthdata_login()

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
                        if _link_matches_layer_filter(link, self.layer_filter):
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
        _earthdata_login()
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
        self.rubber_band = QgsRubberBand(
            self.canvas, QgsWkbTypes.GeometryType.PolygonGeometry
        )
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
        self.rubber_band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
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
        self._footprint_highlight_layer = None

        # Rectangle drawing tool
        self._rectangle_tool = None
        self._previous_map_tool = None

        # Selection sync guard flag
        self._sync_in_progress = False
        self._active_workers = []

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._setup_ui()

    def _track_worker(self, worker):
        """Keep a worker referenced while its native thread may still be running."""
        self._prune_finished_workers()
        self._active_workers.append(worker)

    def _prune_finished_workers(self):
        """Drop worker references only after their native threads have stopped."""
        active = []
        for worker in self._active_workers:
            try:
                if worker.isRunning():
                    active.append(worker)
            except RuntimeError:
                pass
        self._active_workers = active

    def _is_project_layer_alive(self, layer):
        """Return True if a stored QGIS layer wrapper still points to a live layer."""
        if layer is None:
            return False
        try:
            return layer.id() in QgsProject.instance().mapLayers()
        except RuntimeError:
            return False

    def _clear_deleted_footprint_references(self):
        """Clear cached footprint layer wrappers after QGIS deletes the C++ object."""
        if not self._is_project_layer_alive(self._footprint_layer):
            self._footprint_layer = None
        if not self._is_project_layer_alive(self._footprint_highlight_layer):
            self._footprint_highlight_layer = None

    def _make_section_collapsible(self, group, settings_name):
        """Make a group box collapse its contents while keeping the title visible."""
        settings_key = f"NasaOpera/section_{settings_name}_visible"
        is_visible = self.settings.value(settings_key, True, type=bool)

        group.setCheckable(True)
        group.setChecked(is_visible)
        group.setToolTip("Uncheck to hide this section")
        group.toggled.connect(
            lambda visible, section=group, key=settings_key: self._on_section_toggled(
                section, key, visible
            )
        )
        self._set_section_content_visible(group, is_visible)

    def _on_section_toggled(self, group, settings_key, visible):
        """Persist and apply a collapsible section visibility change."""
        self._set_section_content_visible(group, visible)
        self.settings.setValue(settings_key, visible)

    def _set_section_content_visible(self, group, visible):
        """Show or hide every layout item inside a collapsible group box."""
        layout = group.layout()
        if layout is not None:
            for index in range(layout.count()):
                self._set_layout_item_visible(layout.itemAt(index), visible)

        if visible:
            group.setMaximumHeight(16777215)
        else:
            collapsed_height = group.fontMetrics().height() + 18
            group.setMaximumHeight(collapsed_height)

        layout = group.layout()
        if layout is not None:
            layout.activate()
        group.updateGeometry()
        parent = group.parentWidget()
        if parent is not None:
            parent.updateGeometry()
        self._resize_splitter_section(group, visible)

    def _set_layout_item_visible(self, item, visible):
        """Recursively show or hide widgets owned by a layout item."""
        if item is None:
            return

        widget = item.widget()
        if widget is not None:
            widget.setVisible(visible)
            return

        child_layout = item.layout()
        if child_layout is None:
            return

        for index in range(child_layout.count()):
            self._set_layout_item_visible(child_layout.itemAt(index), visible)

    def _resize_splitter_section(self, group, visible):
        """Adjust splitter space when a split section is expanded or collapsed."""
        parent = group.parentWidget()
        if not isinstance(parent, QSplitter):
            return

        section_index = parent.indexOf(group)
        sizes = parent.sizes()
        if section_index < 0 or section_index >= len(sizes):
            return

        if visible:
            sizes[section_index] = max(sizes[section_index], group.sizeHint().height())
        else:
            sizes[section_index] = group.maximumHeight()
        parent.setSizes(sizes)

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
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self._make_section_collapsible(dataset_group, "dataset")

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
        self.bbox_input.setPlaceholderText(
            "xmin, ymin, xmax, ymax (blank uses current map extent)"
        )
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
        self._make_section_collapsible(search_group, "search_parameters")

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
        self.granule_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.granule_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.granule_table.setColumnCount(4)
        self.granule_table.setHorizontalHeaderLabels(
            ["Granule ID", "Begin Date", "End Date", "Links"]
        )
        self.granule_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.granule_table.horizontalHeader().setStretchLastSection(True)
        self.granule_table.setSortingEnabled(True)
        self.granule_table.setMinimumHeight(120)
        self.granule_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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

        # Display-time NoData option
        nodata_layout = QHBoxLayout()
        self.nodata_check = QCheckBox("Treat value as NoData")
        self.nodata_check.setToolTip(
            "Render matching raster pixels as transparent when layers are added"
        )
        self.nodata_value_spin = QDoubleSpinBox()
        self.nodata_value_spin.setDecimals(6)
        self.nodata_value_spin.setRange(-1_000_000_000, 1_000_000_000)
        self.nodata_value_spin.setValue(
            self.settings.value("NasaOpera/display_nodata_value", 0.0, type=float)
        )
        self.nodata_value_spin.setEnabled(False)
        self.nodata_value_spin.setToolTip(
            "Raster value to mark as NoData, for example 0"
        )
        apply_nodata = self.settings.value(
            "NasaOpera/display_apply_nodata", False, type=bool
        )
        self.nodata_check.setChecked(apply_nodata)
        self.nodata_value_spin.setEnabled(apply_nodata)
        self.nodata_check.toggled.connect(self.nodata_value_spin.setEnabled)
        self.nodata_check.toggled.connect(self._save_display_nodata_settings)
        self.nodata_value_spin.valueChanged.connect(self._save_display_nodata_settings)
        nodata_layout.addWidget(self.nodata_check)
        nodata_layout.addWidget(self.nodata_value_spin)
        layer_layout.addRow("NoData:", nodata_layout)

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

        # Output area
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_layout.setContentsMargins(6, 6, 6, 6)
        output_layout.setSpacing(0)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(140)
        self.output_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.output_text.setPlaceholderText(
            "Search results and status messages will appear here..."
        )
        self.output_text.setStyleSheet("font-family: monospace; font-size: 10px;")
        output_layout.addWidget(self.output_text)

        output_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.results_output_splitter = QSplitter(Qt.Orientation.Vertical)
        self.results_output_splitter.setChildrenCollapsible(False)
        self.results_output_splitter.setHandleWidth(6)
        self.results_output_splitter.addWidget(results_group)
        self.results_output_splitter.addWidget(output_group)
        self._make_section_collapsible(results_group, "results")
        self._make_section_collapsible(output_group, "output")
        self.results_output_splitter.setStretchFactor(0, 3)
        self.results_output_splitter.setStretchFactor(1, 2)
        self.results_output_splitter.setSizes([360, 220])
        layout.addWidget(self.results_output_splitter, stretch=1)

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
            bbox = self._current_map_extent_bbox()
            self.bbox_input.setText(self._format_bbox(bbox))

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to get map extent: {str(e)}")

    def _current_map_extent_bbox(self):
        """Return the current map canvas extent as an EPSG:4326 bbox tuple."""
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()

        source_crs = canvas.mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if source_crs != dest_crs:
            transform = QgsCoordinateTransform(
                source_crs, dest_crs, QgsProject.instance()
            )
            extent = transform.transformBoundingBox(extent)

        return (
            extent.xMinimum(),
            extent.yMinimum(),
            extent.xMaximum(),
            extent.yMaximum(),
        )

    def _format_bbox(self, bbox):
        """Format a bbox tuple for display in the bbox input."""
        xmin, ymin, xmax, ymax = bbox
        return f"{xmin:.6f}, {ymin:.6f}, {xmax:.6f}, {ymax:.6f}"

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
        else:
            try:
                bbox = self._current_map_extent_bbox()
                self.output_text.clear()
                self.output_text.append(
                    f"Using current map extent: {self._format_bbox(bbox)}"
                )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Bounding box is blank and the current map extent could not "
                    f"be read:\n{str(e)}",
                )
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
        if bbox_text:
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
        self._track_worker(self._search_worker)
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
            id_item.setData(Qt.ItemDataRole.UserRole, i)  # Store granule index
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
            links_item.setData(Qt.ItemDataRole.DisplayRole, num_links)  # Numeric sort
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
            self._clear_deleted_footprint_references()
            if self._footprint_layer is not None:
                self._sync_in_progress = True
                try:
                    self._footprint_layer.removeSelection()
                    self._update_footprint_highlight([])
                except RuntimeError:
                    self._clear_deleted_footprint_references()
                finally:
                    self._sync_in_progress = False
            return

        # Get the first selected granule to populate layer dropdown
        first_row = min(selected_rows)
        item = self.granule_table.item(first_row, 0)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)

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
            filename = _filename_from_url(link)
            if filename.lower().endswith(RASTER_EXTENSIONS):
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
        self._clear_deleted_footprint_references()
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
                    granule_index = item.data(Qt.ItemDataRole.UserRole)
                    if granule_index is not None:
                        feature_ids.append(granule_index)

            try:
                self._footprint_layer.selectByIds(feature_ids)
                self._update_footprint_highlight(feature_ids)
            except (Exception, RuntimeError):
                self._clear_deleted_footprint_references()
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

        self._clear_deleted_footprint_references()
        if self._footprint_layer is None:
            return

        self._sync_in_progress = True
        try:
            # Get selected feature IDs from the layer
            selected_fids = self._footprint_layer.selectedFeatureIds()
            self._update_footprint_highlight(selected_fids)

            # Build a mapping from granule_index to table row
            index_to_row = {}
            for row in range(self.granule_table.rowCount()):
                item = self.granule_table.item(row, 0)
                if item is not None:
                    granule_index = item.data(Qt.ItemDataRole.UserRole)
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
        except RuntimeError:
            self._clear_deleted_footprint_references()
        finally:
            self._sync_in_progress = False

    def _ensure_footprint_highlight_layer(self):
        """Create the selected-footprint overlay layer when needed."""
        self._clear_deleted_footprint_references()
        if self._footprint_layer is None:
            return None

        if self._footprint_highlight_layer is not None:
            return self._footprint_highlight_layer

        from qgis.core import QgsFillSymbol

        crs = self._footprint_layer.crs()
        crs_authid = crs.authid() if crs.isValid() else "EPSG:4326"
        highlight_layer = QgsVectorLayer(
            f"Polygon?crs={crs_authid}",
            "OPERA Selected Footprints",
            "memory",
        )

        symbol = QgsFillSymbol.createSimple(
            {
                "color": "255,235,59,110",
                "outline_color": "255,255,0,255",
                "outline_width": "1.4",
            }
        )
        highlight_layer.renderer().setSymbol(symbol)
        QgsProject.instance().addMapLayer(highlight_layer)
        self._footprint_highlight_layer = highlight_layer
        return highlight_layer

    def _update_footprint_highlight(self, feature_ids):
        """Mirror selected footprint geometries into the highlight overlay layer."""
        self._clear_deleted_footprint_references()
        if self._footprint_layer is None:
            return

        highlight_layer = self._ensure_footprint_highlight_layer()
        if highlight_layer is None:
            return

        provider = highlight_layer.dataProvider()
        existing_ids = [feature.id() for feature in highlight_layer.getFeatures()]
        if existing_ids:
            provider.deleteFeatures(existing_ids)

        highlight_features = []
        for feature_id in feature_ids:
            # Stale ids can survive a search refresh; skip silently.
            try:
                source_feature = self._footprint_layer.getFeature(feature_id)
            except Exception:  # nosec B112
                continue

            if not source_feature.isValid() or not source_feature.hasGeometry():
                continue

            highlight_feature = QgsFeature()
            highlight_feature.setGeometry(QgsGeometry(source_feature.geometry()))
            highlight_features.append(highlight_feature)

        if highlight_features:
            provider.addFeatures(highlight_features)

        highlight_layer.updateExtents()
        highlight_layer.triggerRepaint()
        self.iface.mapCanvas().refresh()

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
        granule_index = self.granule_table.item(first_row, 0).data(
            Qt.ItemDataRole.UserRole
        )
        if granule_index is None or granule_index >= len(self._results):
            QMessageBox.warning(self, "Error", "No valid granule selected")
            return

        granule = self._results[granule_index]
        layer_name = os.path.splitext(self.layer_combo.currentText())[0]

        # Check if it's a COG (GeoTIFF) file - try streaming first
        is_tif = _filename_from_url(url).lower().endswith((".tif", ".tiff"))

        if is_tif:
            self._set_busy_state(True)
            self.status_label.setText(f"Loading COG: {layer_name}...")
            self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
            self.output_text.append(f"\nTrying to stream COG: {layer_name}")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self._pending_single_download = {
                "granule": granule,
                "url": url,
                "layer_name": layer_name,
            }
            self._cog_stream_worker = CogStreamWorker(url, layer_name)
            self._cog_stream_worker.progress.connect(self._on_cog_stream_progress)
            self._cog_stream_worker.ready.connect(self._on_cog_stream_ready)
            self._cog_stream_worker.finished.connect(
                self._on_cog_stream_thread_finished
            )
            self._track_worker(self._cog_stream_worker)
            self._cog_stream_worker.start()
            return

        self._start_single_download(granule, url, layer_name)

    def _start_single_download(self, granule, url, layer_name):
        """Download one raster file in a background worker."""
        self._set_busy_state(True)
        self.status_label.setText(f"Downloading {layer_name}...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
        self.output_text.append(f"Downloading layer: {layer_name}")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        download_dir = self.settings.value("NasaOpera/cache_dir", "")
        if not download_dir:
            download_dir = os.path.join(tempfile.gettempdir(), "nasa_opera_cache")

        self._download_worker = DownloadRasterWorker(
            granule=granule,
            url=url,
            layer_name=layer_name,
            download_dir=download_dir,
        )
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.progress.connect(self._on_download_progress)
        self._track_worker(self._download_worker)
        self._download_worker.start()

    def _on_cog_stream_progress(self, message):
        """Handle COG streaming preparation progress."""
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_cog_stream_ready(self, success, vsi_path, layer_name, error):
        """Handle completion of COG streaming preparation."""
        if success:
            self.progress_bar.setVisible(False)
            try:
                self._add_raster_layer_to_map(vsi_path, layer_name)
                self.status_label.setText(f"Loaded (streaming): {layer_name}")
                self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
                self.output_text.append("Successfully loaded COG via cloud streaming!")
            except Exception as exc:
                self.status_label.setText("Failed to load streamed layer")
                self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
                self.output_text.append(f"Error loading streamed layer: {exc}")
                QMessageBox.critical(
                    self, "Error", f"Failed to load streamed layer:\n{exc}"
                )
            finally:
                self._set_busy_state(False)
                self._pending_single_download = None
            return

        self.output_text.append(f"Cloud access failed: {error}")
        self.output_text.append("Falling back to download...")
        pending = getattr(self, "_pending_single_download", None)
        if pending is None:
            self.progress_bar.setVisible(False)
            self._set_busy_state(False)
            return

        self._start_single_download(
            pending["granule"], pending["url"], pending["layer_name"]
        )
        self._pending_single_download = None

    def _on_cog_stream_thread_finished(self):
        """Release the COG worker only after Qt reports the thread is stopped."""
        worker = self.sender() or self._cog_stream_worker
        if worker is not None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            worker.deleteLater()
        if self._cog_stream_worker is worker:
            self._cog_stream_worker = None

    def _set_busy_state(self, busy: bool):
        """Set operation controls to busy or ready state.

        Args:
            busy: True to disable operation buttons, False to restore them.
        """
        if busy:
            self.display_single_btn.setEnabled(False)
            self.display_mosaic_btn.setEnabled(False)
            self.download_single_layer_btn.setEnabled(False)
            self.download_all_layers_btn.setEnabled(False)
        else:
            # Re-enable buttons based on selection state
            selected_rows = set()
            for item in self.granule_table.selectedItems():
                selected_rows.add(item.row())
            num_selected = len(selected_rows)
            self.display_single_btn.setEnabled(num_selected == 1)
            self.display_mosaic_btn.setEnabled(num_selected >= 1)
            self.download_single_layer_btn.setEnabled(num_selected >= 1)
            self.download_all_layers_btn.setEnabled(num_selected >= 1)

    def _save_display_nodata_settings(self, *_args):
        """Persist the display-time raster NoData option."""
        self.settings.setValue(
            "NasaOpera/display_apply_nodata", self.nodata_check.isChecked()
        )
        self.settings.setValue(
            "NasaOpera/display_nodata_value", self.nodata_value_spin.value()
        )

    def _apply_display_nodata(self, layer):
        """Apply the panel NoData setting to a raster layer before display."""
        if not self.nodata_check.isChecked():
            return False

        value = self.nodata_value_spin.value()
        try:
            provider = layer.dataProvider()
            band_count = provider.bandCount()
        except Exception as exc:
            self.output_text.append(
                f"  Warning: Could not inspect raster bands for NoData: {exc}"
            )
            return False

        nodata_ranges = [QgsRasterRange(value, value)]
        errors = []

        for band in range(1, band_count + 1):
            try:
                provider.setUserNoDataValue(band, nodata_ranges)
            except Exception as exc:
                errors.append(f"band {band}: {exc}")

        if errors:
            self.output_text.append(
                "  Warning: Could not apply NoData value "
                f"{value:g} to {layer.name()} ({'; '.join(errors)})"
            )
            return False

        layer.triggerRepaint()
        self.output_text.append(f"  Applied NoData value {value:g} to {layer.name()}")
        return True

    def _add_raster_layer_to_map(self, path: str, layer_name: str):
        """Add a raster layer to the project and zoom the map canvas to it."""
        layer = QgsRasterLayer(path, layer_name)
        if not layer.isValid():
            raise RuntimeError(f"Layer is not valid: {path}")

        self._apply_display_nodata(layer)
        QgsProject.instance().addMapLayer(layer)

        layer_extent = layer.extent()
        layer_crs = layer.crs()
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        if layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs:
            transform = QgsCoordinateTransform(
                layer_crs, canvas_crs, QgsProject.instance()
            )
            layer_extent = transform.transformBoundingBox(layer_extent)

        self.iface.mapCanvas().setExtent(layer_extent)
        self.iface.mapCanvas().refresh()
        return layer

    def _add_raster_layers_to_map(self, path: str, layer_name: str):
        """Add a raster file or its HDF5 subdatasets to the map."""
        try:
            sources = _displayable_gdal_sources(path, layer_name)
        except Exception as exc:
            if _is_hdf5_path(path):
                raise RuntimeError(f"Could not inspect HDF5 file: {exc}") from exc
            sources = [(path, layer_name)]

        if not sources:
            if _is_hdf5_path(path):
                raise RuntimeError(
                    "The HDF5 file does not contain displayable raster bands. "
                    "This OPERA file appears to contain metadata only."
                )
            sources = [(path, layer_name)]

        layers = []
        combined_extent = None

        for source, source_layer_name in sources:
            layer = QgsRasterLayer(source, source_layer_name)
            if not layer.isValid():
                raise RuntimeError(f"Layer is not valid: {source}")

            self._apply_display_nodata(layer)
            QgsProject.instance().addMapLayer(layer)
            layers.append(layer)

            layer_extent = layer.extent()
            layer_crs = layer.crs()
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

            if layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(
                    layer_crs, canvas_crs, QgsProject.instance()
                )
                layer_extent = transform.transformBoundingBox(layer_extent)

            if combined_extent is None:
                combined_extent = QgsRectangle(layer_extent)
            else:
                combined_extent.combineExtentWith(layer_extent)

        if combined_extent is not None:
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        return layers

    def _on_download_progress(self, message):
        """Handle download progress update."""
        self.status_label.setText(message)
        self.output_text.append(message)

    def _on_download_finished(self, file_path, layer_name):
        """Handle download completion and add layer to map."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        try:
            layers = self._add_raster_layers_to_map(file_path, layer_name)
            if len(layers) == 1:
                self.status_label.setText(f"Loaded: {layers[0].name()}")
            else:
                self.status_label.setText(
                    f"Loaded {len(layers)} HDF5 raster subdatasets"
                )
            self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
            self.output_text.append(f"Successfully loaded layer: {layer_name}")
            self.output_text.append(f"File: {file_path}")

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
        """Display a virtual mosaic from selected granules."""
        selected_rows = set()
        for item in self.granule_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            QMessageBox.warning(self, "Error", "No granules selected")
            return

        layer_band = self._get_layer_band()
        if not layer_band:
            QMessageBox.warning(self, "Error", "No layer type selected")
            return

        num_selected = len(selected_rows)
        selected_granules = []
        for row in sorted(selected_rows):
            granule_index = self.granule_table.item(row, 0).data(
                Qt.ItemDataRole.UserRole
            )
            if granule_index is None or granule_index >= len(self._results):
                continue

            granule = self._results[granule_index]
            data_links = granule.data_links() if hasattr(granule, "data_links") else []
            selected_granules.append(
                {
                    "granule_id": self.granule_table.item(row, 0).text(),
                    "data_links": data_links,
                }
            )

        if not selected_granules:
            QMessageBox.warning(self, "Error", "No valid granules selected")
            return

        self._set_busy_state(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, num_selected)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Creating mosaic from {num_selected} granules...")
        self.status_label.setStyleSheet("color: #64B5F6; font-size: 10px;")
        self.output_text.append(f"\nCreating mosaic from {num_selected} granules...")
        self.output_text.append(f"Layer band: {layer_band}")

        self._mosaic_worker = MosaicBuildWorker(selected_granules, layer_band)
        self._mosaic_worker.progress.connect(self._on_mosaic_progress)
        self._mosaic_worker.progress_value.connect(self.progress_bar.setValue)
        self._mosaic_worker.ready.connect(self._on_mosaic_ready)
        self._mosaic_worker.error.connect(self._on_mosaic_error)
        self._mosaic_worker.finished.connect(self._on_mosaic_thread_finished)
        self._track_worker(self._mosaic_worker)
        self._mosaic_worker.start()

    def _on_mosaic_progress(self, message):
        """Handle mosaic build progress."""
        self.status_label.setText(message.strip() or "Building mosaic...")
        self.output_text.append(message)

    def _on_mosaic_ready(self, result):
        """Handle background mosaic completion and add VRT layers to QGIS."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        layers_created = []
        combined_extent = None

        for layer_info in result["layers"]:
            layer = QgsRasterLayer(layer_info["path"], layer_info["layer_name"])
            if not layer.isValid():
                self.output_text.append(
                    f"  Warning: Failed to load VRT layer for "
                    f"{layer_info['crs_name']}"
                )
                continue

            self._apply_display_nodata(layer)
            QgsProject.instance().addMapLayer(layer)
            layers_created.append(layer)

            layer_extent = layer.extent()
            layer_crs = layer.crs()
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

            if layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(
                    layer_crs, canvas_crs, QgsProject.instance()
                )
                layer_extent = transform.transformBoundingBox(layer_extent)

            if combined_extent is None:
                combined_extent = QgsRectangle(layer_extent)
            else:
                combined_extent.combineExtentWith(layer_extent)

            self.output_text.append(f"  Layer added: {layer_info['layer_name']}")

        if not layers_created:
            self.status_label.setText("Mosaic failed")
            self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
            error_msg = "Failed to create any mosaic layers"
            self.output_text.append(f"\nError creating mosaic: {error_msg}")
            QMessageBox.critical(
                self, "Mosaic Error", f"Failed to create mosaic:\n{error_msg}"
            )
            return

        if combined_extent:
            combined_extent.scale(1.05)
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        self.status_label.setText(f"Created {len(layers_created)} mosaic layer(s)")
        self.status_label.setStyleSheet("color: #66BB6A; font-size: 10px;")
        self.output_text.append(
            f"\nSuccessfully created {len(layers_created)} mosaic layer(s) "
            f"with {result['total_files']} scenes total!"
        )

    def _on_mosaic_error(self, error_msg):
        """Handle background mosaic errors."""
        self.progress_bar.setVisible(False)
        self._set_busy_state(False)

        self.status_label.setText("Mosaic failed")
        self.status_label.setStyleSheet("color: #EF5350; font-size: 10px;")
        self.output_text.append(f"\nError creating mosaic: {error_msg}")
        QMessageBox.critical(
            self, "Mosaic Error", f"Failed to create mosaic:\n{error_msg}"
        )

    def _on_mosaic_thread_finished(self):
        """Release the mosaic worker only after Qt reports the thread is stopped."""
        worker = self.sender() or self._mosaic_worker
        if worker is not None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            worker.deleteLater()
        if self._mosaic_worker is worker:
            self._mosaic_worker = None

    def _remove_footprint_layer(self):
        """Remove the footprint layer from the map if it exists."""
        if self._footprint_highlight_layer is not None:
            try:
                layer_id = self._footprint_highlight_layer.id()
                if layer_id in QgsProject.instance().mapLayers():
                    QgsProject.instance().removeMapLayer(layer_id)
            except RuntimeError:
                pass
            self._footprint_highlight_layer = None

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
            if lyr.name().startswith("OPERA Footprints") or lyr.name().startswith(
                "OPERA Selected Footprints"
            ):
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

            # Save GeoDataFrame to GeoJSON using to_json() to avoid fiona dependency
            geojson_str = self._gdf.to_json()
            with open(geojson_path, "w", encoding="utf-8") as f:
                f.write(geojson_str)

            # Create and add vector layer
            layer_name = f"OPERA Footprints ({len(self._gdf)})"
            layer = QgsVectorLayer(geojson_path, layer_name, "ogr")

            # Ensure WGS84 CRS (GeoJSON spec mandates it)
            if layer.isValid() and not layer.crs().isValid():
                layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

            if layer.isValid():
                # Style the layer
                from qgis.core import QgsSimpleFillSymbolLayer, QgsFillSymbol

                symbol = QgsFillSymbol.createSimple(
                    {
                        "color": "65,105,225,80",  # Royal blue with transparency
                        "outline_color": "65,105,225,255",
                        "outline_width": "0.8",
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
            index = self.granule_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
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

        if layer_filename.lower().endswith(HDF5_EXTENSIONS):
            return layer_filename

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
        self._track_worker(self._download_granules_worker)
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

        # Clean up any running worker threads.
        workers = list(self._active_workers)
        for attr_name in (
            "_cog_stream_worker",
            "_download_granules_worker",
            "_download_worker",
            "_mosaic_worker",
            "_search_worker",
        ):
            worker = getattr(self, attr_name, None)
            if worker is not None and worker not in workers:
                workers.append(worker)

        for worker in workers:
            if worker is not None:
                if hasattr(worker, "cancel"):
                    try:
                        worker.cancel()
                    except Exception as exc:
                        print(
                            f"NASA OPERA: worker.cancel() failed: {exc}",
                            file=sys.stderr,
                        )
                if hasattr(worker, "wait"):
                    try:
                        worker.wait()
                    except Exception as exc:
                        print(
                            f"NASA OPERA: worker.wait() failed: {exc}",
                            file=sys.stderr,
                        )

        self._active_workers.clear()
        event.accept()
