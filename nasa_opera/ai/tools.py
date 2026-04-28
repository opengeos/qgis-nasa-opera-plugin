"""GeoAgent-backed tools for the NASA OPERA AI assistant.

This module keeps the plugin's existing AI assistant contract
(``ToolRegistry`` and ``create_default_registry``), but delegates the actual
tool implementations to GeoAgent. The dock widget still owns the LLM loop and
the QThread/main-thread signal bridge, which is important because QGIS/PyQt
objects must be touched from the GUI thread.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def _json_safe(value: Any) -> Any:
    """Return a JSON-friendly value for tool results."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parameters_from_tool(tool: Any) -> Dict[str, Any]:
    """Extract an OpenAI-compatible JSON schema from a GeoAgent tool."""
    spec = getattr(tool, "tool_spec", {}) or {}
    schema = spec.get("inputSchema", {}).get("json", {})
    if not schema:
        schema = {"type": "object", "properties": {}, "required": []}
    return schema


def _bbox_string_to_zoom_args(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the legacy ``bbox`` string to ``zoom_to_extent`` arguments."""
    bbox_str = str(kwargs.get("bbox", "")).strip()
    if not bbox_str:
        raise ValueError("bbox is required: 'west,south,east,north'")
    try:
        parts = [float(x.strip()) for x in bbox_str.split(",")]
    except ValueError as exc:
        raise ValueError(f"Invalid bbox format: '{bbox_str}'") from exc
    if len(parts) != 4:
        raise ValueError("bbox must have exactly 4 values: west,south,east,north")
    west, south, east, north = parts
    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "crs": "EPSG:4326",
    }


class BaseTool:
    """Small compatibility base class for plugin tool registries."""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    requires_main_thread: bool = True

    def execute(self, iface, **kwargs) -> Dict[str, Any]:
        """Execute the tool."""
        raise NotImplementedError


class GeoAgentTool(BaseTool):
    """Adapter from a GeoAgent/Strands tool to the plugin tool interface."""

    def __init__(
        self,
        tool: Any,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        argument_adapter: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        result_adapter: Optional[Callable[[Any], Any]] = None,
    ):
        spec = getattr(tool, "tool_spec", {}) or {}
        self._tool = tool
        self._argument_adapter = argument_adapter
        self._result_adapter = result_adapter
        self.name = name or getattr(tool, "tool_name", spec.get("name", ""))
        self.description = description or spec.get("description", "")
        self.parameters = parameters or _parameters_from_tool(tool)

    def execute(self, iface, **kwargs) -> Dict[str, Any]:
        """Execute the wrapped GeoAgent tool."""
        kwargs.pop("_shared_state", None)
        if self._argument_adapter is not None:
            kwargs = self._argument_adapter(kwargs)
        result = self._tool(**kwargs)
        if self._result_adapter is not None:
            result = self._result_adapter(result)
        result = _json_safe(result)
        if isinstance(result, dict):
            return result
        return {"result": result}


class AliasTool(BaseTool):
    """Compatibility alias for old NASA OPERA assistant tool names."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        target: BaseTool,
        argument_adapter: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        result_adapter: Optional[Callable[[Any], Any]] = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._target = target
        self._argument_adapter = argument_adapter
        self._result_adapter = result_adapter

    def execute(self, iface, **kwargs) -> Dict[str, Any]:
        """Execute the target tool using alias-compatible arguments."""
        kwargs.pop("_shared_state", None)
        if self._argument_adapter is not None:
            kwargs = self._argument_adapter(kwargs)
        result = self._target.execute(iface, **kwargs)
        if self._result_adapter is not None:
            result = self._result_adapter(result)
        result = _json_safe(result)
        if isinstance(result, dict):
            return result
        return {"result": result}


class GetMapStateTool(BaseTool):
    """Compatibility map-state tool that reports the current extent in WGS84."""

    name = "get_map_state"
    description = "Get the current QGIS map extent, CRS, scale, and layer count."
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, iface, **kwargs) -> Dict[str, Any]:
        """Return current map state using the old plugin response shape."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )

        canvas = iface.mapCanvas()
        extent = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()
        project_crs = crs.authid() if hasattr(crs, "authid") else "unknown"

        if project_crs != "EPSG:4326":
            transform = QgsCoordinateTransform(
                crs,
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance(),
            )
            extent = transform.transformBoundingBox(extent)

        return {
            "extent": {
                "west": round(float(extent.xMinimum()), 6),
                "south": round(float(extent.yMinimum()), 6),
                "east": round(float(extent.xMaximum()), 6),
                "north": round(float(extent.yMaximum()), 6),
            },
            "crs": "EPSG:4326",
            "project_crs": project_crs,
            "scale": canvas.scale() if hasattr(canvas, "scale") else None,
            "num_layers": len(QgsProject.instance().mapLayers()),
        }


class ToolRegistry:
    """Registry exposing GeoAgent tools to the plugin LLM loop."""

    def __init__(self, iface=None, project=None):
        """Initialize the registry.

        Args:
            iface: Optional QGIS interface. If omitted, tools are loaded lazily
                on the first execute call.
            project: Optional QGIS project instance.
        """
        self._tools: Dict[str, BaseTool] = {}
        self._iface = iface
        self._project = project
        self._load_error: Optional[str] = None
        self.shared_state: Dict[str, Any] = {}
        if iface is not None:
            self._load_geoagent_tools(iface, project)

    def register(self, tool: BaseTool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return OpenAI function-calling schemas for all tools.

        If the registry was created without an ``iface`` (and tools have not
        been loaded yet), this triggers a load attempt so callers that need
        schemas up front, such as the legacy ``OperaAgent`` loop, do not see
        an empty registry.
        """
        if not self._tools and self._iface is not None:
            self._load_geoagent_tools(self._iface, self._project)
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def execute_tool(
        self, name: str, arguments: Dict[str, Any], iface
    ) -> Dict[str, Any]:
        """Execute a tool by name."""
        if not self._tools and iface is not None:
            # Allow recovery when GeoAgent was installed mid-session: clear
            # any prior load error and retry the import/load step.
            self._load_error = None
            self._load_geoagent_tools(iface, self._project)

        if self._load_error:
            return {"error": self._load_error}

        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}

        try:
            clean_args = dict(arguments or {})
            clean_args["_shared_state"] = self.shared_state
            return tool.execute(iface, **clean_args)
        except Exception as exc:
            return {"error": f"Tool '{name}' failed: {exc}"}

    def _load_geoagent_tools(self, iface, project=None):
        """Load OPERA and QGIS tools from GeoAgent."""
        if self._tools:
            return
        try:
            from geoagent.tools.nasa_opera import nasa_opera_tools
            from geoagent.tools.qgis import qgis_tools
        except Exception as exc:
            self._load_error = (
                "GeoAgent is required for the NASA OPERA AI Assistant. "
                f"Install/import GeoAgent in the QGIS Python environment. ({exc})"
            )
            return

        for tool in nasa_opera_tools(iface, project):
            self.register(GeoAgentTool(tool))
        for tool in qgis_tools(iface, project):
            self.register(GeoAgentTool(tool))

        self._register_compatibility_aliases()

    def _register_compatibility_aliases(self):
        """Add old plugin tool names that the assistant prompt still uses."""
        self.register(GetMapStateTool())

        list_layers = self._tools.get("list_project_layers")
        if list_layers is not None:
            self.register(
                AliasTool(
                    name="list_layers",
                    description="List all layers in the current QGIS project.",
                    parameters={"type": "object", "properties": {}, "required": []},
                    target=list_layers,
                    result_adapter=lambda result: {"layers": result},
                )
            )

        zoom_to_extent = self._tools.get("zoom_to_extent")
        if zoom_to_extent is not None:
            self.register(
                AliasTool(
                    name="set_map_extent",
                    description=(
                        "Pan and zoom the QGIS map to a specific geographic "
                        "bounding box. Coordinates should be in decimal degrees "
                        "(WGS84)."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "bbox": {
                                "type": "string",
                                "description": (
                                    "Bounding box as 'west,south,east,north' in "
                                    "decimal degrees. E.g., "
                                    "'-95.5,29.5,-95.0,30.0'."
                                ),
                            },
                        },
                        "required": ["bbox"],
                    },
                    target=zoom_to_extent,
                    argument_adapter=_bbox_string_to_zoom_args,
                    result_adapter=lambda result: {"success": True, "message": result},
                )
            )


def create_default_registry(iface=None, project=None) -> ToolRegistry:
    """Create the GeoAgent-backed tool registry used by the AI assistant."""
    return ToolRegistry(iface=iface, project=project)
