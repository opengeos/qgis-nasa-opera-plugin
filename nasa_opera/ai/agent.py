"""
Agent Loop for NASA OPERA Plugin.

Orchestrates the conversation between the user, the LLM, and the agent tools.
Handles multi-turn tool calling, streaming responses, and conversation history.
"""

import json
from typing import Any, Dict, List, Optional

from .tools import ToolRegistry

# System prompt providing OPERA domain knowledge and tool usage instructions
SYSTEM_PROMPT = """\
You are an AI assistant embedded in a QGIS plugin for NASA OPERA \
(Observational Products for End-Users from Remote Sensing Analysis) \
satellite data. You help users search, visualize, and analyze OPERA \
data products using natural language.

## Available OPERA Datasets

1. **OPERA_L3_DSWX-HLS_V1** - Dynamic Surface Water Extent from \
Harmonized Landsat Sentinel-2. Shows where surface water is present.
2. **OPERA_L3_DSWX-S1_V1** - Dynamic Surface Water Extent from \
Sentinel-1 SAR. Water detection using radar (works through clouds).
3. **OPERA_L3_DIST-ALERT-HLS_V1** - Land Surface Disturbance Alert. \
Near real-time alerts for vegetation/land disturbance events.
4. **OPERA_L3_DIST-ANN-HLS_V1** - Land Surface Disturbance Annual. \
Yearly summary of land surface disturbance.
5. **OPERA_L2_RTC-S1_V1** - Radiometric Terrain Corrected SAR \
Backscatter from Sentinel-1. Analysis-ready radar imagery.
6. **OPERA_L2_RTC-S1-STATIC_V1** - RTC-S1 Static Layers. \
Supplementary static data for RTC-S1.
7. **OPERA_L2_CSLC-S1_V1** - Coregistered Single-Look Complex from \
Sentinel-1. Precise radar phase data for interferometry.
8. **OPERA_L2_CSLC-S1-STATIC_V1** - CSLC-S1 Static Layers. \
Supplementary static data for CSLC-S1.

## Guidelines

- When the user asks about water or flooding, suggest DSWX-HLS or \
DSWX-S1 datasets.
- When the user asks about deforestation, fire damage, or land \
disturbance, suggest DIST-ALERT or DIST-ANN datasets.
- When the user asks about SAR or radar data, suggest RTC-S1 or CSLC-S1.
- Always search before trying to display data.
- When displaying rasters, pick a specific data_link URL from the \
search results.
- Use the current map extent when no specific location is given.
- Display tools (display_raster, create_mosaic, display_footprints) \
do NOT change the map zoom. Use set_map_extent BEFORE adding layers \
to zoom to the area of interest, so the view stays correct after \
layers are loaded.
- Provide concise explanations of what you found and displayed.
- When reporting search results, summarize key details (count, date \
range, coverage).
"""


class OperaAgent:
    """Orchestrates the agent conversation loop."""

    def __init__(
        self,
        llm_client: Any,
        tool_registry: ToolRegistry,
        iface,
    ):
        """Initialize the agent.

        Args:
            llm_client: Configured LLM client.
            tool_registry: Registry of available tools.
            iface: QGIS interface instance.
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.iface = iface
        self.history: List[Dict] = []
        self.max_history_messages = 40
        self._cached_map_state: Optional[str] = None

    def capture_map_state(self):
        """Capture current map state on the main thread.

        Must be called from the main thread before process_message()
        runs on a worker thread, since QGIS API is not thread-safe.
        """
        map_tool = self.tool_registry.get_tool("get_map_state")
        if map_tool:
            try:
                state = map_tool.execute(self.iface)
                ext = state.get("extent", {})
                self._cached_map_state = (
                    f"\n\n## Current Map State\n"
                    f"- Extent: ({ext.get('west')}, {ext.get('south')}, "
                    f"{ext.get('east')}, {ext.get('north')})\n"
                    f"- CRS: {state.get('crs', 'unknown')}\n"
                    f"- Loaded layers: {state.get('num_layers', 0)}"
                )
            except Exception:
                self._cached_map_state = None

    def _build_system_message(self) -> Dict:
        """Build the system message with cached map context.

        Returns:
            System message dict.
        """
        map_state_str = self._cached_map_state or ""
        return {
            "role": "system",
            "content": SYSTEM_PROMPT + map_state_str,
        }

    def _truncate_history(self):
        """Keep conversation history within token limits."""
        if len(self.history) > self.max_history_messages:
            # Keep first message (might be important context) and recent messages
            self.history = (
                self.history[:1] + self.history[-(self.max_history_messages - 1) :]
            )

    def process_message(
        self,
        user_message: str,
        on_text_chunk=None,
        on_tool_call=None,
        on_tool_result=None,
        execute_tool_fn=None,
    ) -> str:
        """Process a user message through the agent loop.

        Args:
            user_message: The user's natural language input.
            on_text_chunk: Callback(chunk: str) for streaming text.
            on_tool_call: Callback(tool_name: str, args: dict) when a tool is called.
            on_tool_result: Callback(tool_name: str, result: dict) when tool completes.
            execute_tool_fn: Function(name, args) -> dict to execute tools
                (for main-thread execution). If None, executes directly.

        Returns:
            The complete assistant response text.
        """
        self.history.append({"role": "user", "content": user_message})
        self._truncate_history()

        messages = [self._build_system_message()] + self.history
        tools = self.tool_registry.get_tool_definitions()

        max_iterations = 10
        full_response = ""

        for _ in range(max_iterations):
            response = self.llm_client.complete(
                messages=messages,
                tools=tools if tools else None,
                stream=False,
            )

            choice = response.choices[0]
            message = choice.message

            # Check for tool calls
            if message.tool_calls:
                # Add assistant message with tool calls to history
                self.history.append(message.model_dump())
                messages.append(message.model_dump())

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    if on_tool_call:
                        on_tool_call(tool_name, tool_args)

                    # Execute tool
                    if execute_tool_fn:
                        result = execute_tool_fn(tool_name, tool_args)
                    else:
                        result = self.tool_registry.execute_tool(
                            tool_name, tool_args, self.iface
                        )

                    if on_tool_result:
                        on_tool_result(tool_name, result)

                    # Add tool result to messages
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                    self.history.append(tool_message)
                    messages.append(tool_message)

                # Continue the loop to get the next response
                continue

            # No tool calls -- this is the final text response
            content = message.content or ""
            full_response = content

            if on_text_chunk:
                on_text_chunk(content)

            self.history.append({"role": "assistant", "content": content})
            break

        return full_response

    def clear_history(self):
        """Clear conversation history."""
        self.history.clear()
