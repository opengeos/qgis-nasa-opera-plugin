"""
Agent Tools for NASA OPERA Plugin.

Defines the ToolRegistry and core tools that the AI agent can use to search,
display, and analyze NASA OPERA data within QGIS.
"""

import json
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional


class BaseTool:
    """Base class for agent tools."""

    name: str = ""
    description: str = ""
    parameters: Dict = {}
    requires_main_thread: bool = False

    def execute(self, iface, **kwargs) -> Dict:
        """Execute the tool.

        Args:
            iface: QGIS interface instance.
            **kwargs: Tool-specific arguments.

        Returns:
            Dict with result data.
        """
        raise NotImplementedError


class ToolRegistry:
    """Registry managing available agent tools."""

    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, BaseTool] = {}
        self.shared_state: Dict[str, Any] = {}

    def register(self, tool: BaseTool):
        """Register a tool.

        Args:
            tool: Tool instance to register.
        """
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self._tools.get(name)

    def get_tool_definitions(self) -> List[Dict]:
        """Get tool definitions in OpenAI function-calling format.

        Returns:
            List of tool definition dicts for litellm.
        """
        definitions = []
        for tool in self._tools.values():
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return definitions

    def execute_tool(self, name: str, arguments: Dict, iface) -> Dict:
        """Execute a tool by name.

        Args:
            name: Tool name.
            arguments: Tool arguments.
            iface: QGIS interface instance.

        Returns:
            Dict with result data.
        """
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        try:
            # Pass shared state reference so tools can communicate
            arguments["_shared_state"] = self.shared_state
            return tool.execute(iface, **arguments)
        except Exception as e:
            return {"error": f"Tool '{name}' failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Core Tool Implementations
# ---------------------------------------------------------------------------


class GetAvailableDatasetsTool(BaseTool):
    """List all available NASA OPERA datasets."""

    name = "get_available_datasets"
    description = (
        "List all available NASA OPERA satellite data products "
        "with their short names and descriptions."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, iface, **kwargs) -> Dict:
        """Return all OPERA dataset metadata."""
        from ..dialogs.opera_dock import OPERA_DATASETS

        datasets = []
        for short_name, info in OPERA_DATASETS.items():
            datasets.append(
                {
                    "short_name": short_name,
                    "title": info["title"],
                    "short_title": info["short_title"],
                    "description": info["description"],
                }
            )
        return {"datasets": datasets}


class GetDatasetInfoTool(BaseTool):
    """Get detailed info about a specific OPERA dataset."""

    name = "get_dataset_info"
    description = (
        "Get detailed information about a specific NASA OPERA dataset "
        "by its short name or keyword."
    )
    parameters = {
        "type": "object",
        "properties": {
            "dataset_name": {
                "type": "string",
                "description": (
                    "Dataset short name (e.g., 'OPERA_L3_DSWX-HLS_V1') "
                    "or keyword to search (e.g., 'water', 'disturbance', 'SAR')."
                ),
            }
        },
        "required": ["dataset_name"],
    }

    def execute(self, iface, **kwargs) -> Dict:
        """Return info about a matching dataset."""
        from ..dialogs.opera_dock import OPERA_DATASETS

        query = kwargs.get("dataset_name", "").upper()
        matches = []

        for short_name, info in OPERA_DATASETS.items():
            if query in short_name or query in info["title"].upper():
                matches.append(
                    {
                        "short_name": short_name,
                        "title": info["title"],
                        "short_title": info["short_title"],
                        "description": info["description"],
                    }
                )

        if not matches:
            return {"error": f"No dataset matching '{kwargs.get('dataset_name', '')}'."}
        return {"datasets": matches}


class SearchOperaDataTool(BaseTool):
    """Search NASA OPERA data."""

    name = "search_opera_data"
    description = (
        "Search NASA OPERA satellite data products by dataset type, "
        "geographic bounding box, and date range. Returns a list of "
        "granules with metadata and data download links."
    )
    parameters = {
        "type": "object",
        "properties": {
            "dataset": {
                "type": "string",
                "description": (
                    "OPERA dataset short name, e.g., 'OPERA_L3_DSWX-HLS_V1'. "
                    "Use get_available_datasets to see all options."
                ),
            },
            "bbox": {
                "type": "string",
                "description": (
                    "Bounding box as 'west,south,east,north' in decimal degrees "
                    "(WGS84). E.g., '-115.3,36.0,-115.0,36.3' for Las Vegas area. "
                    "If omitted, uses the current QGIS map extent."
                ),
            },
            "start_date": {
                "type": "string",
                "description": "Start date in YYYY-MM-DD format.",
            },
            "end_date": {
                "type": "string",
                "description": "End date in YYYY-MM-DD format.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 20).",
            },
        },
        "required": ["dataset"],
    }
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Search OPERA data using earthaccess."""
        import earthaccess

        from ..dialogs.opera_dock import _earthdata_login

        dataset = kwargs.get("dataset", "")
        bbox_str = kwargs.get("bbox", "")
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        max_results = kwargs.get("max_results", 20)

        # Parse bbox
        bbox = None
        if bbox_str:
            try:
                parts = [float(x.strip()) for x in bbox_str.split(",")]
                if len(parts) == 4:
                    bbox = tuple(parts)
            except ValueError:
                return {"error": f"Invalid bbox format: '{bbox_str}'"}
        else:
            # Use current map extent
            canvas = iface.mapCanvas()
            extent = canvas.extent()
            crs = canvas.mapSettings().destinationCrs()
            if crs.authid() != "EPSG:4326":
                from qgis.core import (
                    QgsCoordinateReferenceSystem,
                    QgsCoordinateTransform,
                    QgsProject,
                )

                transform = QgsCoordinateTransform(
                    crs,
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance(),
                )
                extent = transform.transformBoundingBox(extent)
            bbox = (
                extent.xMinimum(),
                extent.yMinimum(),
                extent.xMaximum(),
                extent.yMaximum(),
            )

        # Authenticate and search
        _earthdata_login()

        search_params = {"short_name": dataset, "count": max_results}
        if bbox:
            search_params["bounding_box"] = bbox
        if start_date and end_date:
            search_params["temporal"] = (start_date, end_date)
        elif start_date:
            from datetime import datetime

            search_params["temporal"] = (
                start_date,
                datetime.today().strftime("%Y-%m-%d"),
            )

        results = earthaccess.search_data(**search_params)

        # Store results in shared state for use by display tools
        shared = kwargs.get("_shared_state", {})
        shared["last_search_results"] = results

        # Build summary
        granules = []
        for granule in results:
            meta = granule.get("meta", {})
            umm = granule.get("umm", {})
            temporal = umm.get("TemporalExtent", {}).get("RangeDateTime", {})
            data_links = granule.data_links() if hasattr(granule, "data_links") else []

            granules.append(
                {
                    "native_id": meta.get("native-id", ""),
                    "begin_date": temporal.get("BeginningDateTime", ""),
                    "end_date": temporal.get("EndingDateTime", ""),
                    "num_links": len(data_links),
                    "data_links": data_links[:3],
                }
            )

        return {
            "count": len(results),
            "dataset": dataset,
            "granules": granules,
        }


class DisplayFootprintsTool(BaseTool):
    """Display search result footprints on the map."""

    name = "display_footprints"
    description = (
        "Display the footprints (geographic outlines) of the most recent "
        "search results on the QGIS map as a vector layer. "
        "Must be called after search_opera_data."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Display footprints from last search results."""
        shared = kwargs.get("_shared_state", {})
        results = shared.get("last_search_results")
        if not results:
            return {"error": "No search results to display."}

        try:
            features = []
            for granule in results:
                meta = granule.get("meta", {})
                umm = granule.get("umm", {})
                spatial = umm.get("SpatialExtent", {})
                horizontal = spatial.get("HorizontalSpatialDomain", {})

                geom = None
                if "Geometry" in horizontal:
                    geo = horizontal["Geometry"]
                    if "BoundingRectangles" in geo:
                        rects = geo["BoundingRectangles"]
                        if rects:
                            r = rects[0]
                            w = r.get("WestBoundingCoordinate", 0)
                            s = r.get("SouthBoundingCoordinate", 0)
                            e = r.get("EastBoundingCoordinate", 0)
                            n = r.get("NorthBoundingCoordinate", 0)
                            geom = {
                                "type": "Polygon",
                                "coordinates": [
                                    [[w, s], [e, s], [e, n], [w, n], [w, s]]
                                ],
                            }
                    elif "GPolygons" in geo:
                        polys = geo["GPolygons"]
                        if polys:
                            boundary = polys[0].get("Boundary", {})
                            points = boundary.get("Points", [])
                            if points:
                                coords = [
                                    [p.get("Longitude", 0), p.get("Latitude", 0)]
                                    for p in points
                                ]
                                # Close the ring
                                if coords and coords[0] != coords[-1]:
                                    coords.append(coords[0])
                                geom = {
                                    "type": "Polygon",
                                    "coordinates": [coords],
                                }

                if geom is None:
                    continue

                temporal = umm.get("TemporalExtent", {}).get("RangeDateTime", {})
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geom,
                        "properties": {
                            "native_id": meta.get("native-id", ""),
                            "begin_date": temporal.get("BeginningDateTime", ""),
                            "end_date": temporal.get("EndingDateTime", ""),
                        },
                    }
                )

            if not features:
                return {"error": "No valid geometries found in results."}

            # Write GeoJSON directly (avoids pyogrio/fiona PROJ issues)
            geojson = {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:4326"},
                },
                "features": features,
            }
            geojson_path = os.path.join(
                tempfile.gettempdir(), "opera_footprints.geojson"
            )
            with open(geojson_path, "w", encoding="utf-8") as f:
                json.dump(geojson, f)

            from qgis.core import QgsFillSymbol, QgsProject, QgsVectorLayer
            from qgis.PyQt.QtGui import QColor

            # Remove existing footprint layers to avoid duplicates
            project = QgsProject.instance()
            for existing in project.mapLayersByName("OPERA Footprints"):
                project.removeMapLayer(existing.id())

            layer = QgsVectorLayer(geojson_path, "OPERA Footprints", "ogr")
            if layer.isValid():
                # Style with semi-transparent fill
                symbol = QgsFillSymbol.createSimple({})
                fill = symbol.symbolLayer(0)
                fill.setColor(QColor(25, 118, 210, 50))
                fill.setStrokeColor(QColor(25, 118, 210, 200))
                fill.setStrokeWidth(0.5)
                layer.renderer().setSymbol(symbol)

                project.addMapLayer(layer)
                iface.mapCanvas().refresh()
                return {
                    "success": True,
                    "message": f"Displayed {len(features)} footprints on the map.",
                }
            return {"error": "Failed to create footprint layer."}

        except Exception as e:
            return {"error": f"Failed to display footprints: {str(e)}"}


class DisplayRasterTool(BaseTool):
    """Load and display a single raster granule."""

    name = "display_raster"
    description = (
        "Load and display a single NASA OPERA raster file on the QGIS map. "
        "Provide a URL from the search results. "
        "Tries cloud-optimized streaming first, falls back to download. "
        "Does not change the map extent -- use set_map_extent to zoom."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of the raster file to display (from search results data_links).",
            },
            "layer_name": {
                "type": "string",
                "description": "Name for the layer in QGIS (optional).",
            },
        },
        "required": ["url"],
    }
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Display a raster from URL."""
        url = kwargs.get("url", "")
        layer_name = kwargs.get("layer_name", url.split("/")[-1])

        if not url:
            return {"error": "No URL provided."}

        from ..dialogs.opera_dock import setup_gdal_for_earthdata, get_vsicurl_path
        from qgis.core import QgsProject, QgsRasterLayer

        # Try COG streaming first
        success, error = setup_gdal_for_earthdata()
        if success:
            vsi_path = get_vsicurl_path(url)
            layer = QgsRasterLayer(vsi_path, layer_name)
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                iface.mapCanvas().refresh()
                return {
                    "success": True,
                    "message": f"Displayed '{layer_name}' via cloud streaming.",
                }

        # Fall back to download
        try:
            import earthaccess

            from ..dialogs.opera_dock import _earthdata_login

            _earthdata_login()

            from qgis.core import QgsSettings

            settings = QgsSettings()
            cache_dir = settings.value("NasaOpera/cache_dir", "") or os.path.join(
                os.path.expanduser("~"), "nasa_opera_cache"
            )
            os.makedirs(cache_dir, exist_ok=True)

            filename = url.split("/")[-1]
            local_path = os.path.join(cache_dir, filename)

            if not os.path.exists(local_path):
                downloaded = earthaccess.download(
                    [url], local_path=cache_dir, threads=1
                )
                if downloaded:
                    local_path = str(downloaded[0])

            layer = QgsRasterLayer(local_path, layer_name)
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                iface.mapCanvas().refresh()
                return {
                    "success": True,
                    "message": f"Displayed '{layer_name}' (downloaded).",
                }
            return {"error": f"Failed to load raster from {local_path}."}

        except Exception as e:
            return {"error": f"Failed to display raster: {str(e)}"}


class CreateMosaicTool(BaseTool):
    """Create a virtual mosaic from multiple granules."""

    name = "create_mosaic"
    description = (
        "Create a virtual mosaic (VRT) from multiple NASA OPERA granule URLs "
        "and display it on the QGIS map. Useful for combining tiles into a "
        "seamless view. Does not change the map extent -- use set_map_extent "
        "to zoom to the area of interest."
    )
    parameters = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of raster file URLs to mosaic together.",
            },
            "layer_name": {
                "type": "string",
                "description": "Name for the mosaic layer (default: 'OPERA Mosaic').",
            },
        },
        "required": ["urls"],
    }
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Create and display a VRT mosaic."""
        urls = kwargs.get("urls", [])
        layer_name = kwargs.get("layer_name", "OPERA Mosaic")

        if not urls:
            return {"error": "No URLs provided."}

        from osgeo import gdal

        from ..dialogs.opera_dock import setup_gdal_for_earthdata, get_vsicurl_path

        success, error = setup_gdal_for_earthdata()
        if not success:
            return {"error": f"Failed to configure GDAL: {error}"}

        vsi_paths = [get_vsicurl_path(u) for u in urls]

        # Verify at least one file is accessible
        accessible = []
        for path in vsi_paths:
            ds = gdal.Open(path)
            if ds:
                accessible.append(path)
                ds = None

        if not accessible:
            return {"error": "None of the provided URLs are accessible."}

        # Build VRT
        vrt_path = os.path.join(tempfile.gettempdir(), f"{layer_name}.vrt")
        vrt_ds = gdal.BuildVRT(vrt_path, accessible)
        if vrt_ds is None:
            return {"error": "Failed to build VRT mosaic."}
        vrt_ds.FlushCache()
        vrt_ds = None

        from qgis.core import QgsProject, QgsRasterLayer

        layer = QgsRasterLayer(vrt_path, layer_name)
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            iface.mapCanvas().refresh()
            return {
                "success": True,
                "message": (
                    f"Created mosaic '{layer_name}' from "
                    f"{len(accessible)} of {len(urls)} tiles."
                ),
            }
        return {"error": "Failed to load VRT mosaic layer."}


class ListLayersTool(BaseTool):
    """List all layers in the QGIS project."""

    name = "list_layers"
    description = (
        "List all layers currently loaded in the QGIS project, "
        "including their names, types (raster/vector), CRS, and visibility."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """List all project layers."""
        from qgis.core import QgsProject

        layers = []
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            layer_type = "unknown"
            if layer.type().value == 0:
                layer_type = "vector"
            elif layer.type().value == 1:
                layer_type = "raster"

            info = {
                "name": layer.name(),
                "type": layer_type,
                "crs": layer.crs().authid() if layer.crs().isValid() else "unknown",
                "visible": (
                    iface.layerTreeView()
                    .layerTreeModel()
                    .rootGroup()
                    .findLayer(layer)
                    .isVisible()
                    if iface.layerTreeView()
                    .layerTreeModel()
                    .rootGroup()
                    .findLayer(layer)
                    else True
                ),
            }

            if layer_type == "raster":
                info["width"] = layer.width()
                info["height"] = layer.height()
                info["band_count"] = layer.bandCount()
            elif layer_type == "vector":
                info["feature_count"] = layer.featureCount()
                info["geometry_type"] = (
                    layer.geometryType().name
                    if hasattr(layer.geometryType(), "name")
                    else str(layer.geometryType())
                )

            layers.append(info)

        return {"layers": layers, "count": len(layers)}


class RemoveLayerTool(BaseTool):
    """Remove a layer from the project."""

    name = "remove_layer"
    description = "Remove a layer from the QGIS project by name."
    parameters = {
        "type": "object",
        "properties": {
            "layer_name": {
                "type": "string",
                "description": "Name of the layer to remove.",
            }
        },
        "required": ["layer_name"],
    }
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Remove a layer by name."""
        from qgis.core import QgsProject

        layer_name = kwargs.get("layer_name", "")
        project = QgsProject.instance()
        layers = project.mapLayersByName(layer_name)

        if not layers:
            return {"error": f"No layer named '{layer_name}' found."}

        for layer in layers:
            project.removeMapLayer(layer.id())

        return {
            "success": True,
            "message": f"Removed {len(layers)} layer(s) named '{layer_name}'.",
        }


class GetMapStateTool(BaseTool):
    """Get the current QGIS map state."""

    name = "get_map_state"
    description = (
        "Get the current QGIS map state including the map extent "
        "(bounding box), coordinate reference system, zoom level, "
        "and number of loaded layers."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Return current map state."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )

        canvas = iface.mapCanvas()
        extent = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()

        # Convert extent to WGS84 for readability
        wgs84_extent = extent
        if crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                crs,
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance(),
            )
            wgs84_extent = transform.transformBoundingBox(extent)

        return {
            "extent": {
                "west": round(wgs84_extent.xMinimum(), 6),
                "south": round(wgs84_extent.yMinimum(), 6),
                "east": round(wgs84_extent.xMaximum(), 6),
                "north": round(wgs84_extent.yMaximum(), 6),
            },
            "crs": crs.authid(),
            "scale": canvas.scale(),
            "num_layers": len(QgsProject.instance().mapLayers()),
        }


class SetMapExtentTool(BaseTool):
    """Set the map extent (pan/zoom)."""

    name = "set_map_extent"
    description = (
        "Pan and zoom the QGIS map to a specific geographic bounding box. "
        "Coordinates should be in decimal degrees (WGS84)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "bbox": {
                "type": "string",
                "description": (
                    "Bounding box as 'west,south,east,north' in decimal degrees. "
                    "E.g., '-95.5,29.5,-95.0,30.0'."
                ),
            }
        },
        "required": ["bbox"],
    }
    requires_main_thread = True

    def execute(self, iface, **kwargs) -> Dict:
        """Set map extent to the given bbox."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
            QgsRectangle,
        )

        bbox_str = kwargs.get("bbox", "")
        try:
            parts = [float(x.strip()) for x in bbox_str.split(",")]
            if len(parts) != 4:
                return {
                    "error": "bbox must have exactly 4 values: west,south,east,north"
                }
        except ValueError:
            return {"error": f"Invalid bbox format: '{bbox_str}'"}

        west, south, east, north = parts
        rect = QgsRectangle(west, south, east, north)

        canvas = iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()

        if canvas_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                canvas_crs,
                QgsProject.instance(),
            )
            rect = transform.transformBoundingBox(rect)

        canvas.setExtent(rect)
        canvas.refresh()

        return {
            "success": True,
            "message": f"Map extent set to ({west}, {south}, {east}, {north}).",
        }


def create_default_registry() -> ToolRegistry:
    """Create a ToolRegistry with all default tools registered.

    Returns:
        A ToolRegistry with all core tools.
    """
    registry = ToolRegistry()

    tools = [
        GetAvailableDatasetsTool(),
        GetDatasetInfoTool(),
        SearchOperaDataTool(),
        DisplayFootprintsTool(),
        DisplayRasterTool(),
        CreateMosaicTool(),
        ListLayersTool(),
        RemoveLayerTool(),
        GetMapStateTool(),
        SetMapExtentTool(),
    ]

    for tool in tools:
        registry.register(tool)

    return registry
