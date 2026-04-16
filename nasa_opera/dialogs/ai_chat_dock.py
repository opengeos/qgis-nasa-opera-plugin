"""
AI Chat Dock Widget for NASA OPERA Plugin.

Provides a conversational interface for interacting with NASA OPERA data
using natural language powered by LLM providers.
"""

import json
import re

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QPlainTextEdit,
    QComboBox,
    QSizePolicy,
    QMessageBox,
)
from qgis.PyQt.QtGui import QFont, QTextCursor, QKeyEvent, QPalette

SUGGESTED_PROMPTS = [
    "What OPERA datasets are available?",
    "Search for surface water data in my current map extent",
    "Find land disturbance alerts in California from 2024",
    "Show me the latest DSWX-HLS data for Las Vegas area",
]


def _is_dark_theme() -> bool:
    """Detect whether the current Qt theme is dark.

    Returns:
        True if the application uses a dark theme.
    """
    palette = QApplication.instance().palette()
    bg = palette.color(QPalette.Window)
    # A window background with lightness below 128 is considered dark
    return bg.lightness() < 128


def _theme_colors() -> dict:
    """Return a dict of colour values that adapt to light/dark theme.

    Returns:
        Dict with keys: accent, accent_hover, text, text_secondary,
        bg_chat, bg_user, bg_assistant, bg_error, bg_suggestion,
        border, tool_color, success, error_color.
    """
    if _is_dark_theme():
        return {
            "accent": "#64B5F6",
            "accent_hover": "#90CAF9",
            "text": "#E0E0E0",
            "text_secondary": "#AAAAAA",
            "bg_chat": "#2B2B2B",
            "bg_user": "#1A3A5C",
            "bg_assistant": "#383838",
            "bg_error": "#4A1C1C",
            "bg_suggestion": "#383838",
            "bg_suggestion_hover": "#1A3A5C",
            "border": "#555555",
            "tool_color": "#64B5F6",
            "success": "#81C784",
            "error_color": "#EF9A9A",
            "user_label": "#90CAF9",
            "assistant_label": "#E0E0E0",
        }
    return {
        "accent": "#1976D2",
        "accent_hover": "#1565C0",
        "text": "#333333",
        "text_secondary": "#888888",
        "bg_chat": "#FAFAFA",
        "bg_user": "#E3F2FD",
        "bg_assistant": "#F5F5F5",
        "bg_error": "#FFEBEE",
        "bg_suggestion": "#FFFFFF",
        "bg_suggestion_hover": "#E3F2FD",
        "border": "#E0E0E0",
        "tool_color": "#1976D2",
        "success": "#388E3C",
        "error_color": "#D32F2F",
        "user_label": "#1565C0",
        "assistant_label": "#333333",
    }


def _welcome_html(colors: dict) -> str:
    """Build the welcome HTML using theme-appropriate colours.

    Args:
        colors: Theme colour dict from _theme_colors().

    Returns:
        HTML string for the welcome message.
    """
    return (
        f'<div style="color: {colors["text"]}; padding: 10px;">'
        f'<h3 style="color: {colors["accent"]};">NASA OPERA AI Assistant</h3>'
        "<p>Ask me about NASA OPERA satellite data. I can help you:</p>"
        "<ul>"
        "<li>Search for OPERA data products by location and date</li>"
        "<li>Display satellite imagery and footprints on the map</li>"
        "<li>Create mosaics from multiple granules</li>"
        "<li>Get information about available datasets</li>"
        "</ul>"
        f'<p style="color: {colors["text_secondary"]}; font-size: 11px;">'
        "Configure your LLM provider in Settings &gt; AI Assistant tab."
        "</p></div>"
    )


class ChatInputWidget(QPlainTextEdit):
    """Custom text input that sends on Enter and allows Shift+Enter for newlines."""

    def __init__(self, send_callback, parent=None):
        """Initialize the chat input widget.

        Args:
            send_callback: Function to call when Enter is pressed.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._send_callback = send_callback
        self.setPlaceholderText("Ask about OPERA data...")
        self.setMaximumHeight(80)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events.

        Args:
            event: The key event.
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self._send_callback()
                return
        super().keyPressEvent(event)


class AIChatDockWidget(QDockWidget):
    """AI Chat interface dock widget."""

    SETTINGS_PREFIX = "NasaOpera/"

    def __init__(self, iface, parent=None):
        """Initialize the AI chat dock widget.

        Args:
            iface: QGIS interface instance.
            parent: Parent widget.
        """
        super().__init__("AI Assistant", parent)
        self.iface = iface
        self.settings = QSettings()
        self._worker = None
        self._agent = None
        self._tool_registry = None

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._colors = _theme_colors()
        self._setup_ui()

    def _setup_ui(self):
        """Set up the chat UI."""
        c = self._colors

        main_widget = QWidget()
        self.setWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        # Header with provider selector
        header_layout = QHBoxLayout()

        header_label = QLabel("AI Assistant")
        header_font = QFont()
        header_font.setPointSize(11)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {c['accent']};")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        # Provider/model display
        self.provider_label = QLabel("")
        self.provider_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 10px;"
        )
        header_layout.addWidget(self.provider_label)

        layout.addLayout(header_layout)

        # Chat display
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {c['bg_chat']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: 12px;
            }}
        """)
        self.chat_display.setHtml(_welcome_html(c))
        layout.addWidget(self.chat_display, stretch=1)

        # Suggested prompts (shown initially)
        self.suggestions_widget = QWidget()
        suggestions_layout = QVBoxLayout(self.suggestions_widget)
        suggestions_layout.setContentsMargins(0, 0, 0, 0)
        suggestions_layout.setSpacing(4)

        suggestions_label = QLabel("Try asking:")
        suggestions_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 10px;"
        )
        suggestions_layout.addWidget(suggestions_label)

        for prompt_text in SUGGESTED_PROMPTS:
            btn = QPushButton(prompt_text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 6px 10px;
                    border: 1px solid {c['border']};
                    border-radius: 4px;
                    background-color: {c['bg_suggestion']};
                    color: {c['text']};
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {c['bg_suggestion_hover']};
                    border-color: {c['accent']};
                }}
            """)
            btn.clicked.connect(lambda checked, t=prompt_text: self._send_suggested(t))
            suggestions_layout.addWidget(btn)

        layout.addWidget(self.suggestions_widget)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 10px; padding: 2px;"
        )
        layout.addWidget(self.status_label)

        # Input area
        input_layout = QHBoxLayout()
        input_layout.setSpacing(4)

        self.chat_input = ChatInputWidget(self._on_send)
        input_layout.addWidget(self.chat_input, stretch=1)

        # Button column
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['accent']};
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
                min-height: 28px;
            }}
            QPushButton:hover {{ background-color: {c['accent_hover']}; }}
            QPushButton:disabled {{ background-color: #666666; color: #999999; }}
        """)
        self.send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self.send_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #D32F2F;
                color: white;
                padding: 4px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #C62828; }
        """)
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setVisible(False)
        btn_layout.addWidget(self.stop_btn)

        input_layout.addLayout(btn_layout)
        layout.addLayout(input_layout)

        # Bottom buttons
        bottom_layout = QHBoxLayout()

        self.clear_btn = QPushButton("Clear Chat")
        self.clear_btn.setStyleSheet("font-size: 10px; padding: 3px 8px;")
        self.clear_btn.clicked.connect(self._on_clear)
        bottom_layout.addWidget(self.clear_btn)

        bottom_layout.addStretch()

        layout.addLayout(bottom_layout)

        # Update provider label
        self._update_provider_label()

    def _update_provider_label(self):
        """Update the provider/model display label."""
        provider = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_provider", "", type=str
        )
        model = self.settings.value(f"{self.SETTINGS_PREFIX}ai_model", "", type=str)
        if provider and model:
            self.provider_label.setText(f"{provider}/{model}")
        elif provider:
            self.provider_label.setText(provider)
        else:
            self.provider_label.setText("Not configured")

    def _ensure_agent(self) -> bool:
        """Ensure the agent is initialized with current settings.

        Only recreates the agent if settings have changed or no agent exists.
        Preserves conversation history across setting changes.

        Returns:
            True if agent is ready, False if configuration is missing.
        """
        provider = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_provider", "", type=str
        )
        if not provider:
            QMessageBox.warning(
                self,
                "AI Not Configured",
                "Please configure your LLM provider in\n"
                "Settings > AI Assistant tab.",
            )
            return False

        model = self.settings.value(f"{self.SETTINGS_PREFIX}ai_model", "", type=str)
        api_key = self.settings.value(f"{self.SETTINGS_PREFIX}ai_api_key", "", type=str)
        base_url = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_base_url", "", type=str
        )
        temperature_pct = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_temperature", 30, type=int
        )
        temperature = temperature_pct / 100.0
        max_tokens = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_max_tokens", 4096, type=int
        )

        # Ollama doesn't need an API key
        if provider.lower() != "ollama" and not api_key:
            QMessageBox.warning(
                self,
                "API Key Missing",
                f"Please enter your {provider} API key in\n"
                "Settings > AI Assistant tab.",
            )
            return False

        # Check if settings changed -- skip recreation if unchanged
        settings_key = (provider, model, api_key, base_url, temperature, max_tokens)
        if (
            self._agent is not None
            and hasattr(self, "_last_settings_key")
            and self._last_settings_key == settings_key
        ):
            return True

        from ..ai.llm_client import LLMClient, DEFAULT_MODELS
        from ..ai.tools import create_default_registry
        from ..ai.agent import OperaAgent

        if not model:
            model = DEFAULT_MODELS.get(provider.lower(), "")

        client = LLMClient(
            provider=provider,
            model=model,
            api_key=api_key if api_key else None,
            base_url=base_url if base_url else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Preserve conversation history if agent existed
        old_history = self._agent.history if self._agent else []

        self._tool_registry = create_default_registry()
        self._agent = OperaAgent(client, self._tool_registry, self.iface)
        self._agent.history = old_history
        self._last_settings_key = settings_key
        self._update_provider_label()
        return True

    def _send_suggested(self, text: str):
        """Send a suggested prompt.

        Args:
            text: The suggested prompt text.
        """
        self.chat_input.setPlainText(text)
        self._on_send()

    def _on_send(self):
        """Handle sending a message."""
        message = self.chat_input.toPlainText().strip()
        if not message:
            return

        if not self._ensure_agent():
            return

        # Capture map state on main thread before entering worker
        self._agent.capture_map_state()

        # Hide suggestions after first message
        self.suggestions_widget.setVisible(False)

        # Display user message
        self._append_user_message(message)
        self.chat_input.clear()

        # Disable input during processing
        c = self._colors
        self.send_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.chat_input.setEnabled(False)
        self.status_label.setText("Thinking...")
        self.status_label.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")

        # Start agent worker
        from ..ai.workers import AgentWorker

        self._worker = AgentWorker(self._agent, message)
        self._worker.text_chunk.connect(self._on_text_chunk)
        self._worker.tool_call_started.connect(self._on_tool_call_started)
        self._worker.tool_call_result.connect(self._on_tool_call_result)
        self._worker.execute_tool_request.connect(self._on_execute_tool_request)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stop(self):
        """Handle stop button click."""
        if self._worker:
            self._worker.cancel()
            # Unblock worker if waiting for tool result
            self._worker.provide_tool_result({"error": "Operation cancelled by user."})
        self._reset_input_state()
        self.status_label.setText("Cancelled")
        self.status_label.setStyleSheet(
            f"color: {self._colors['error_color']}; font-size: 10px;"
        )

    def _on_clear(self):
        """Clear the chat history."""
        self._colors = _theme_colors()
        self.chat_display.setHtml(_welcome_html(self._colors))
        self.suggestions_widget.setVisible(True)
        if self._agent:
            self._agent.clear_history()
        self.status_label.setText("Chat cleared")
        self.status_label.setStyleSheet(
            f"color: {self._colors['text_secondary']}; font-size: 10px;"
        )

    def _on_text_chunk(self, chunk: str):
        """Handle streaming text from the agent.

        Args:
            chunk: Text chunk from the LLM.
        """
        self._append_assistant_message(chunk)

    def _on_tool_call_started(self, tool_name: str, args_json: str):
        """Handle tool call start notification.

        Args:
            tool_name: Name of the tool being called.
            args_json: JSON string of tool arguments.
        """
        c = self._colors
        try:
            args = json.loads(args_json)
            args_display = ", ".join(
                f"{k}={v}" for k, v in args.items() if not k.startswith("_")
            )
        except (json.JSONDecodeError, AttributeError):
            args_display = ""

        tool_html = (
            f'<div style="color: {c["tool_color"]}; font-size: 11px; '
            f'padding: 2px 0;">'
            f"<b>Running:</b> {tool_name}"
        )
        if args_display:
            tool_html += f" ({args_display})"
        tool_html += "</div>"

        self.chat_display.append(tool_html)
        self._scroll_to_bottom()

        self.status_label.setText(f"Executing: {tool_name}...")
        self.status_label.setStyleSheet(f"color: {c['tool_color']}; font-size: 10px;")

    def _on_tool_call_result(self, tool_name: str, result_json: str):
        """Handle tool execution result.

        Args:
            tool_name: Name of the tool.
            result_json: JSON string of the result.
        """
        c = self._colors
        try:
            result = json.loads(result_json)
            err_color = c["error_color"]
            ok_color = c["success"]
            muted = c["text_secondary"]
            if "error" in result:
                status = (
                    f"<span style='color: {err_color};'>"
                    f"Error: {result['error']}</span>"
                )
            elif "success" in result:
                msg = result.get("message", "Done")
                status = f"<span style='color: {ok_color};'>{msg}</span>"
            elif "count" in result:
                status = (
                    f"<span style='color: {ok_color};'>"
                    f"Found {result['count']} results</span>"
                )
            else:
                status = f"<span style='color: {ok_color};'>Done</span>"
        except (json.JSONDecodeError, AttributeError):
            muted = c["text_secondary"]
            status = f"<span style='color: {muted};'>Completed</span>"

        result_html = (
            f'<div style="font-size: 11px; padding: 0 0 4px 10px;">' f"{status}</div>"
        )
        self.chat_display.append(result_html)
        self._scroll_to_bottom()

    def _on_execute_tool_request(self, tool_name: str, args_json: str):
        """Execute a tool on the main thread (QGIS API safe).

        Args:
            tool_name: Name of the tool to execute.
            args_json: JSON string of tool arguments.
        """
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            args = {}

        result = self._tool_registry.execute_tool(tool_name, args, self.iface)

        if self._worker:
            self._worker.provide_tool_result(result)

    def _on_finished(self, response: str):
        """Handle agent completion.

        Args:
            response: The full response text.
        """
        self._reset_input_state()
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet(
            f"color: {self._colors['success']}; font-size: 10px;"
        )

    def _on_error(self, error_msg: str):
        """Handle agent error.

        Args:
            error_msg: Error message.
        """
        self._append_error_message(error_msg)
        self._reset_input_state()
        self.status_label.setText("Error occurred")
        self.status_label.setStyleSheet(
            f"color: {self._colors['error_color']}; font-size: 10px;"
        )

    def _reset_input_state(self):
        """Re-enable input controls after processing."""
        self.send_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()
        self._worker = None

    def _append_user_message(self, message: str):
        """Append a user message to the chat display.

        Args:
            message: The user's message text.
        """
        c = self._colors
        escaped = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        escaped = escaped.replace("\n", "<br>")
        html = (
            f'<div style="background-color: {c["bg_user"]}; '
            f"border-radius: 8px; padding: 8px 12px; "
            f'margin: 4px 20px 4px 60px; color: {c["text"]};">'
            f'<b style="color: {c["user_label"]};">You</b><br>'
            f"{escaped}</div>"
        )
        self.chat_display.append(html)
        self._scroll_to_bottom()

    def _append_assistant_message(self, message: str):
        """Append an assistant message to the chat display.

        Args:
            message: The assistant's message text.
        """
        c = self._colors
        formatted = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        formatted = formatted.replace("\n", "<br>")

        # Bold
        formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", formatted)
        # Inline code
        formatted = re.sub(r"`(.+?)`", r"<code>\1</code>", formatted)

        html = (
            f'<div style="background-color: {c["bg_assistant"]}; '
            f"border-radius: 8px; padding: 8px 12px; "
            f'margin: 4px 60px 4px 0px; color: {c["text"]};">'
            f'<b style="color: {c["assistant_label"]};">Assistant</b><br>'
            f"{formatted}</div>"
        )
        self.chat_display.append(html)
        self._scroll_to_bottom()

    def _append_error_message(self, message: str):
        """Append an error message to the chat display.

        Args:
            message: The error message text.
        """
        c = self._colors
        escaped = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        html = (
            f'<div style="background-color: {c["bg_error"]}; '
            f"border-radius: 8px; padding: 8px 12px; margin: 4px 0; "
            f'color: {c["text"]};">'
            f'<b style="color: {c["error_color"]};">Error</b><br>'
            f"{escaped}</div>"
        )
        self.chat_display.append(html)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll the chat display to the bottom."""
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
