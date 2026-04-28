"""
AI Chat Dock Widget for NASA OPERA Plugin.

Provides a conversational interface for interacting with NASA OPERA data
using natural language powered by LLM providers.
"""

import json
import re
import html
import time
import traceback

from qgis.PyQt.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QDockWidget,
    QLineEdit,
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
from qgis.PyQt.QtGui import QFont, QGuiApplication, QTextCursor, QKeyEvent, QPalette

SUGGESTED_PROMPTS = [
    "What OPERA datasets are available?",
    "Search for surface water data in my current map extent",
    "Find land disturbance alerts in California from 2024",
    "Show me the latest DSWX-HLS data for Las Vegas area",
]


class GeoAgentOperaWorker(QThread):
    """Run GeoAgent NASA OPERA chat without blocking the QGIS UI.

    GeoAgent's NASA OPERA and QGIS tools wrap their QGIS/PyQt operations in
    ``run_on_qt_gui_thread`` (``QMetaObject.invokeMethod`` with
    ``BlockingQueuedConnection``), so executing ``agent.chat()`` from this
    worker thread is the supported pattern: tool work that touches QGIS
    objects is marshalled back to the GUI thread automatically.
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        iface,
        prompt,
        provider,
        model_id,
        fast,
        max_tokens,
        agent=None,
        parent=None,
    ):
        """Initialize the worker."""
        super().__init__(parent)
        self.iface = iface
        self.prompt = prompt
        self.provider = provider
        self.model_id = model_id or None
        self.fast = fast
        self.max_tokens = max_tokens
        self.agent = agent

    def _confirm_unless_interrupted(self, request):
        """Confirm tool execution unless the worker was asked to stop.

        Returning ``False`` cancels the upcoming tool call; GeoAgent treats a
        cancelled tool as a stop reason and ends the chat loop, which gives
        the Stop button a clean way to abort an in-flight request without
        killing the underlying network or model call mid-stream.
        """
        return not self.isInterruptionRequested()

    def run(self):
        """Create a GeoAgent NASA OPERA agent and execute one chat turn."""
        try:
            from geoagent import GeoAgentConfig, for_nasa_opera

            agent = self.agent
            if agent is None:
                config = GeoAgentConfig(
                    provider=self.provider,
                    model=self.model_id,
                    max_tokens=self.max_tokens,
                )
                agent = for_nasa_opera(
                    self.iface,
                    project=None,
                    config=config,
                    fast=self.fast,
                    confirm=self._confirm_unless_interrupted,
                )
            response = agent.chat(self.prompt)
            self.finished.emit(
                {
                    "success": bool(response.success),
                    "answer": response.answer_text or "",
                    "error": response.error_message or "",
                    "tools": ", ".join(response.executed_tools or []),
                    "cancelled": ", ".join(response.cancelled_tools or []),
                    "elapsed": f"{response.execution_time:.2f}s",
                    "agent": agent,
                    "interrupted": self.isInterruptionRequested(),
                }
            )
        except Exception as exc:
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")


def _plain_text_to_html(text: str) -> str:
    """Convert plain text to basic HTML."""
    return html.escape(text).replace("\n", "<br>")


def _inline_markdown_to_html(text: str) -> str:
    """Convert inline Markdown spans to HTML."""
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


def _is_markdown_table(lines: list[str], index: int) -> bool:
    """Return True if lines at index start a simple Markdown table."""
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    separator = lines[index + 1].strip()
    if "|" not in header or "|" not in separator:
        return False
    separator_cells = [cell.strip() for cell in separator.strip("|").split("|")]
    return bool(separator_cells) and all(
        re.match(r"^:?-{3,}:?$", cell) for cell in separator_cells
    )


def _table_to_html(table_lines: list[str]) -> str:
    """Convert a simple Markdown pipe table to HTML."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in table_lines
    ]
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = rows[2:]
    header_html = "".join(
        f"<th>{_inline_markdown_to_html(cell)}</th>" for cell in header
    )
    body_rows = []
    for row in body:
        cells = "".join(f"<td>{_inline_markdown_to_html(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        "<table style='border-collapse: collapse; width: 100%; margin: 6px 0;'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _markdown_to_basic_html(markdown: str) -> str:
    """Render common Markdown to HTML for QTextBrowser."""
    lines = markdown.splitlines()
    html_lines: list[str] = []
    in_ul = False
    in_ol = False
    in_code = False
    code_lines: list[str] = []
    i = 0

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                html_lines.append(
                    f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>"
                )
                code_lines = []
                in_code = False
            else:
                close_lists()
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if _is_markdown_table(lines, i):
            close_lists()
            table_lines = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            html_lines.append(_table_to_html(table_lines))
            continue

        if not stripped:
            close_lists()
            html_lines.append("")
            i += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            close_lists()
            level = len(heading.group(1))
            html_lines.append(
                f"<h{level}>{_inline_markdown_to_html(heading.group(2))}</h{level}>"
            )
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{_inline_markdown_to_html(bullet.group(1))}</li>")
            i += 1
            continue

        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if numbered:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{_inline_markdown_to_html(numbered.group(1))}</li>")
            i += 1
            continue

        close_lists()
        html_lines.append(f"<p>{_inline_markdown_to_html(stripped)}</p>")
        i += 1

    if in_code:
        html_lines.append(
            f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>"
        )
    close_lists()
    return "\n".join(html_lines)


def _is_dark_theme() -> bool:
    """Detect whether the current Qt theme is dark.

    Returns:
        True if the application uses a dark theme.
    """
    palette = QApplication.instance().palette()
    bg = palette.color(QPalette.ColorRole.Window)
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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
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
        self._agent_settings_key = None
        self._messages = []
        self._last_assistant_markdown = ""
        self._status_started_at = None
        self._status_base_text = "Thinking"
        self._status_frame = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._update_running_status)

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._colors = _theme_colors()
        self._setup_ui()
        self._load_model_settings()

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

        # Model controls match qgis_geoagent's provider selection pattern.
        from ..ai.model_config import PROVIDERS

        model_group = QGroupBox("Model")
        model_layout = QFormLayout(model_group)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(PROVIDERS)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        model_layout.addRow("Provider:", self.provider_combo)

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Use provider default")
        model_layout.addRow("Model:", self.model_input)

        self.fast_check = QCheckBox("Fast mode")
        model_layout.addRow("", self.fast_check)

        layout.addWidget(model_group)

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

        self.copy_md_btn = QPushButton("Copy Markdown")
        self.copy_md_btn.setStyleSheet("font-size: 10px; padding: 3px 8px;")
        self.copy_md_btn.setEnabled(False)
        self.copy_md_btn.clicked.connect(self._copy_latest_markdown)
        bottom_layout.addWidget(self.copy_md_btn)

        bottom_layout.addStretch()

        layout.addLayout(bottom_layout)

        # Update provider label
        self._update_provider_label()

    def _update_provider_label(self):
        """Update the provider/model display label."""
        if hasattr(self, "provider_combo") and hasattr(self, "model_input"):
            provider = self.provider_combo.currentText()
            model = self.model_input.text().strip()
        else:
            from ..ai.model_config import model_from_settings, provider_from_settings

            provider = provider_from_settings(self.settings)
            model = model_from_settings(self.settings, provider)
        if provider and model:
            self.provider_label.setText(f"{provider}/{model}")
        elif provider:
            self.provider_label.setText(provider)
        else:
            self.provider_label.setText("Not configured")

    def _load_model_settings(self):
        """Load persisted model settings into the dock controls."""
        from ..ai.model_config import DEFAULT_MODELS, provider_from_settings, setting

        provider = provider_from_settings(self.settings)
        index = self.provider_combo.findText(provider)
        self.provider_combo.setCurrentIndex(index if index >= 0 else 1)

        model = setting(self.settings, "ai_model", "")
        self.model_input.setText(model or DEFAULT_MODELS.get(provider, ""))
        self.fast_check.setChecked(setting(self.settings, "ai_fast_mode", False, bool))
        self._update_provider_label()

    def _save_model_settings(self):
        """Persist the selected provider, model, and fast-mode setting."""
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_provider", self.provider_combo.currentText()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_model", self.model_input.text()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_fast_mode", self.fast_check.isChecked()
        )

    def _on_provider_changed(self, provider):
        """Update the model field when provider changes."""
        from ..ai.model_config import DEFAULT_MODELS

        self.model_input.setText(DEFAULT_MODELS.get(provider, ""))
        self._agent = None
        self._agent_settings_key = None
        self._update_provider_label()

    def _ensure_agent(self) -> bool:
        """Ensure GeoAgent and provider dependencies are importable.

        Returns:
            True if the assistant can start, False otherwise.
        """
        try:
            from geoagent import GeoAgentConfig, for_nasa_opera  # noqa: F401
        except Exception as exc:
            QMessageBox.warning(
                self,
                "GeoAgent Not Available",
                "The AI Assistant requires GeoAgent provider dependencies.\n\n"
                f"{exc}\n\nOpen Settings > AI Assistant to install dependencies.",
            )
            return False

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
        self.status_label.setStyleSheet(f"color: {c['accent']}; font-size: 10px;")
        self._start_running_status("Thinking")

        from ..ai.model_config import apply_environment_from_settings, setting

        self._save_model_settings()
        apply_environment_from_settings(self.settings)
        provider = self.provider_combo.currentText()
        model_id = self.model_input.text().strip()
        fast = self.fast_check.isChecked()
        max_tokens = setting(self.settings, "ai_max_tokens", 4096, int)
        settings_key = (provider, model_id, fast, max_tokens)
        if self._agent_settings_key != settings_key:
            self._agent = None
            self._agent_settings_key = settings_key

        self._worker = GeoAgentOperaWorker(
            self.iface,
            message,
            provider,
            model_id,
            fast,
            max_tokens,
            self._agent,
            self,
        )
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_stop(self):
        """Handle stop button click."""
        worker = self._worker
        if worker is not None:
            # Ask the worker's confirm callback to reject the next tool call,
            # which lets GeoAgent end the chat loop cleanly instead of leaving
            # the QThread running with no way to cancel.
            worker.requestInterruption()
            # Late signals from this worker are now stale; drop them in the
            # finished/error handlers.
            worker._discarded = True
            self._worker = None
        self._reset_input_state()
        self.status_label.setText("Cancelling...")
        self.status_label.setStyleSheet(
            f"color: {self._colors['error_color']}; font-size: 10px;"
        )

    def _on_clear(self):
        """Clear the chat history."""
        self._colors = _theme_colors()
        self._messages = []
        self._last_assistant_markdown = ""
        self._agent = None
        self._agent_settings_key = None
        self.copy_md_btn.setEnabled(False)
        self._render_transcript()
        self.suggestions_widget.setVisible(True)
        self.status_label.setText("Chat cleared")
        self.status_label.setStyleSheet(
            f"color: {self._colors['text_secondary']}; font-size: 10px;"
        )

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

        self._start_running_status(f"Executing: {tool_name}")
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

    def _on_finished(self, result: dict):
        """Handle agent completion.

        Args:
            result: Worker result payload.
        """
        sender = self.sender()
        if getattr(sender, "_discarded", False) or (
            self._worker is not None and sender is not self._worker
        ):
            # The user pressed Stop or started a newer turn before this one
            # arrived; ignore late signals from the stale worker.
            return
        self._agent = result.get("agent") or self._agent
        if result.get("interrupted"):
            self._append_error_message("Cancelled by user.")
            self._reset_input_state()
            self.status_label.setText("Cancelled")
            self.status_label.setStyleSheet(
                f"color: {self._colors['error_color']}; font-size: 10px;"
            )
            self._worker = None
            return
        if result.get("success"):
            answer = result.get("answer") or "(No text response.)"
            details = []
            if result.get("tools"):
                details.append(f"Tools: {result['tools']}")
            if result.get("elapsed"):
                details.append(f"Elapsed: {result['elapsed']}")
            if details:
                answer = f"{answer}\n\n" + "\n".join(details)
            self._append_assistant_message(answer)
        else:
            error = result.get("error") or "Unknown error"
            cancelled = result.get("cancelled")
            if cancelled:
                error = f"{error}\nCancelled tools: {cancelled}"
            self._append_error_message(error)
            self._reset_input_state()
            self.status_label.setText("Error occurred")
            self.status_label.setStyleSheet(
                f"color: {self._colors['error_color']}; font-size: 10px;"
            )
            self._worker = None
            return

        self._reset_input_state()
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet(
            f"color: {self._colors['success']}; font-size: 10px;"
        )
        self._worker = None

    def _on_error(self, error_msg: str):
        """Handle agent error.

        Args:
            error_msg: Error message.
        """
        sender = self.sender()
        if getattr(sender, "_discarded", False) or (
            self._worker is not None and sender is not self._worker
        ):
            return
        self._append_error_message(error_msg)
        self._reset_input_state()
        self.status_label.setText("Error occurred")
        self.status_label.setStyleSheet(
            f"color: {self._colors['error_color']}; font-size: 10px;"
        )
        self._worker = None

    def _reset_input_state(self):
        """Re-enable input controls after processing."""
        self._stop_running_status()
        self.send_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()
        self._worker = None

    def _start_running_status(self, base_text: str):
        """Start or update the animated status text."""
        self._status_base_text = base_text
        if self._status_started_at is None:
            self._status_started_at = time.monotonic()
            self._status_frame = 0
        if not self._status_timer.isActive():
            self._status_timer.start()
        self._update_running_status()

    def _stop_running_status(self):
        """Stop the animated status text."""
        if self._status_timer.isActive():
            self._status_timer.stop()
        self._status_started_at = None
        self._status_frame = 0

    def _update_running_status(self):
        """Refresh the animated status text."""
        if self._status_started_at is None:
            return
        elapsed = int(time.monotonic() - self._status_started_at)
        spinner = ("-", "\\", "|", "/")[self._status_frame % 4]
        self._status_frame += 1
        dots = "." * (self._status_frame % 4)
        if elapsed >= 30:
            suffix = "large OPERA rasters can take a while"
        elif elapsed >= 10:
            suffix = "running tools and waiting for the model"
        else:
            suffix = "working"
        self.status_label.setText(
            f"{spinner} {self._status_base_text}{dots} {elapsed}s - {suffix}"
        )

    def _append_user_message(self, message: str):
        """Append a user message to the chat display.

        Args:
            message: The user's message text.
        """
        self._append_message("You", message, markdown=False)

    def _append_assistant_message(self, message: str):
        """Append an assistant message to the chat display.

        Args:
            message: The assistant's message text.
        """
        self._append_message("Assistant", message, markdown=True)

    def _append_error_message(self, message: str):
        """Append an error message to the chat display.

        Args:
            message: The error message text.
        """
        c = self._colors
        escaped = _plain_text_to_html(message)
        html = (
            f'<div style="background-color: {c["bg_error"]}; '
            f"border-radius: 8px; padding: 8px 12px; margin: 4px 0; "
            f'color: {c["text"]};">'
            f'<b style="color: {c["error_color"]};">Error</b><br>'
            f"{escaped}</div>"
        )
        self._messages.append({"sender": "Error", "body": html, "html": True})
        self._render_transcript()

    def _append_message(self, sender: str, message: str, markdown: bool = False):
        """Append a chat message and refresh the transcript."""
        body = message.strip()
        self._messages.append(
            {"sender": sender, "body": body, "markdown": markdown, "html": False}
        )
        if markdown:
            self._last_assistant_markdown = body
            self.copy_md_btn.setEnabled(True)
        self._render_transcript()

    def _render_transcript(self):
        """Render stored messages as HTML."""
        c = self._colors
        blocks = [_welcome_html(c)]
        for msg in self._messages:
            if msg.get("html"):
                blocks.append(str(msg["body"]))
                continue

            sender = html.escape(str(msg["sender"]))
            is_user = sender == "You"
            bg = c["bg_user"] if is_user else c["bg_assistant"]
            label = c["user_label"] if is_user else c["assistant_label"]
            margin = "4px 0px" if is_user else "4px 0px 4px 0px"
            if msg.get("markdown"):
                body = _markdown_to_basic_html(str(msg["body"]))
            else:
                body = f"<p>{_plain_text_to_html(str(msg['body']))}</p>"
            blocks.append(
                f'<div style="background-color: {bg}; '
                f"border-radius: 8px; padding: 8px 12px; "
                f'margin: {margin}; color: {c["text"]};">'
                f'<p style="font-weight: 600; color: {label}; margin-bottom: 4px;">'
                f"{sender}</p>{body}</div>"
            )
        self.chat_display.setHtml("\n".join(blocks))
        self._scroll_to_bottom()

    def _copy_latest_markdown(self):
        """Copy the latest assistant Markdown response to the clipboard."""
        if not self._last_assistant_markdown:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._last_assistant_markdown)
            self.status_label.setText("Copied latest response as Markdown.")
            self.status_label.setStyleSheet(
                f"color: {self._colors['success']}; font-size: 10px;"
            )

    def _scroll_to_bottom(self):
        """Scroll the chat display to the bottom."""
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
