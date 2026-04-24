"""
Settings Dock Widget for NASA OPERA Plugin

This module provides a settings panel for configuring the NASA OPERA plugin,
including Earthdata credentials and display options.
"""

import sys

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QFormLayout,
    QMessageBox,
    QFileDialog,
    QTabWidget,
    QProgressBar,
)
from qgis.PyQt.QtGui import QFont


class SettingsDockWidget(QDockWidget):
    """A settings panel for configuring plugin options."""

    # Settings keys
    SETTINGS_PREFIX = "NasaOpera/"

    def __init__(self, iface, parent=None):
        """Initialize the settings dock widget.

        Args:
            iface: QGIS interface instance.
            parent: Parent widget.
        """
        super().__init__("NASA OPERA Settings", parent)
        self.iface = iface
        self.settings = QSettings()

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Set up the settings UI."""
        # Main widget
        main_widget = QWidget()
        self.setWidget(main_widget)

        # Main layout
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)

        # Header
        header_label = QLabel("NASA OPERA Settings")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_label.setStyleSheet("color: #1565C0; padding: 5px;")
        layout.addWidget(header_label)

        # Tab widget for organized settings
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Dependencies tab (first, most important for new users)
        dependencies_tab = self._create_dependencies_tab()
        self.tab_widget.addTab(dependencies_tab, "Dependencies")

        # Credentials tab
        credentials_tab = self._create_credentials_tab()
        self.tab_widget.addTab(credentials_tab, "Credentials")

        # Display settings tab
        display_tab = self._create_display_tab()
        self.tab_widget.addTab(display_tab, "Display")

        # Advanced settings tab
        advanced_tab = self._create_advanced_tab()
        self.tab_widget.addTab(advanced_tab, "Advanced")

        # AI Assistant settings tab
        ai_tab = self._create_ai_tab()
        self.tab_widget.addTab(ai_tab, "AI Assistant")

        # Buttons
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        button_layout.addWidget(self.reset_btn)

        layout.addLayout(button_layout)

        # Stretch at the end
        layout.addStretch()

        # Status label
        self.status_label = QLabel("Settings loaded")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.status_label)

    def _create_dependencies_tab(self):
        """Create the dependencies management tab."""
        from ..deps_manager import REQUIRED_PACKAGES

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info label
        info_label = QLabel(
            "The NASA OPERA plugin requires the following Python packages.\n"
            "Click 'Install Dependencies' to install them in an isolated\n"
            "virtual environment that does not affect your QGIS Python."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 10px; padding: 5px;")
        layout.addWidget(info_label)

        # Dependencies status group
        deps_group = QGroupBox("Package Status")
        deps_layout = QVBoxLayout(deps_group)

        self.dep_status_labels = {}
        for import_name, pip_name in REQUIRED_PACKAGES:
            row_layout = QHBoxLayout()
            name_label = QLabel(f"  {pip_name}")
            name_label.setMinimumWidth(100)
            status_label = QLabel("Checking...")
            status_label.setStyleSheet("color: gray;")
            row_layout.addWidget(name_label)
            row_layout.addWidget(status_label)
            row_layout.addStretch()
            deps_layout.addLayout(row_layout)
            self.dep_status_labels[import_name] = status_label

        layout.addWidget(deps_group)

        # Overall status
        self.deps_overall_label = QLabel("Checking dependencies...")
        self.deps_overall_label.setWordWrap(True)
        self.deps_overall_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.deps_overall_label)

        # Progress bar (hidden by default)
        self.deps_progress_bar = QProgressBar()
        self.deps_progress_bar.setRange(0, 100)
        self.deps_progress_bar.setVisible(False)
        layout.addWidget(self.deps_progress_bar)

        # Progress label (hidden by default)
        self.deps_progress_label = QLabel("")
        self.deps_progress_label.setWordWrap(True)
        self.deps_progress_label.setStyleSheet("font-size: 10px;")
        self.deps_progress_label.setVisible(False)
        layout.addWidget(self.deps_progress_label)

        # Install button
        self.install_deps_btn = QPushButton("Install Dependencies")
        self.install_deps_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1565C0;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """)
        self.install_deps_btn.clicked.connect(self._install_dependencies)
        layout.addWidget(self.install_deps_btn)

        # Refresh button
        self.refresh_deps_btn = QPushButton("Refresh Status")
        self.refresh_deps_btn.clicked.connect(self._refresh_dependency_status)
        layout.addWidget(self.refresh_deps_btn)

        layout.addStretch()

        # Note about isolation
        note_label = QLabel(
            "Packages are installed in an isolated environment\n"
            "(~/.qgis_nasa_opera/) and do not affect your QGIS Python.\n"
            "If packages are not detected after installation, restart QGIS."
        )
        note_label.setWordWrap(True)
        note_label.setStyleSheet("font-size: 9px; font-style: italic;")
        layout.addWidget(note_label)

        # Trigger initial status check after UI is constructed
        from qgis.PyQt.QtCore import QTimer

        QTimer.singleShot(100, self._refresh_dependency_status)

        return widget

    def _refresh_dependency_status(self):
        """Check and display the status of all required dependencies."""
        from ..deps_manager import check_dependencies

        deps = check_dependencies()
        all_ok = True

        for dep in deps:
            label = self.dep_status_labels.get(dep["name"])
            if label is None:
                continue
            if dep["installed"]:
                version_str = dep["version"] or "installed"
                label.setText(f"Installed ({version_str})")
                label.setStyleSheet("color: green; font-weight: bold;")
            else:
                label.setText("Not installed")
                label.setStyleSheet("color: red;")
                all_ok = False

        if all_ok:
            self.deps_overall_label.setText("All dependencies are installed.")
            self.deps_overall_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 5px;"
            )
            self.install_deps_btn.setVisible(False)
        else:
            missing_count = sum(1 for d in deps if not d["installed"])
            self.deps_overall_label.setText(
                f"{missing_count} package(s) missing. "
                "Click 'Install Dependencies' to install."
            )
            self.deps_overall_label.setStyleSheet(
                "color: #E65100; font-weight: bold; padding: 5px;"
            )
            self.install_deps_btn.setVisible(True)
            self.install_deps_btn.setEnabled(True)

    def _install_dependencies(self):
        """Start installing missing dependencies in a background thread."""
        from ..deps_manager import DepsInstallWorker

        self.install_deps_btn.setEnabled(False)
        self.install_deps_btn.setText("Installing...")
        self.refresh_deps_btn.setEnabled(False)

        self.deps_progress_bar.setVisible(True)
        self.deps_progress_bar.setValue(0)
        self.deps_progress_label.setVisible(True)
        self.deps_progress_label.setText("Starting installation...")

        self._deps_worker = DepsInstallWorker()
        self._deps_worker.progress.connect(self._on_deps_install_progress)
        self._deps_worker.finished.connect(self._on_deps_install_finished)
        self._deps_worker.start()

    def _on_deps_install_progress(self, percent, message):
        """Handle progress updates from the install worker.

        Args:
            percent: Installation progress percentage (0-100).
            message: Status message to display.
        """
        self.deps_progress_bar.setValue(percent)
        self.deps_progress_label.setText(message)

    def _on_deps_install_finished(self, success, message):
        """Handle completion of dependency installation.

        Args:
            success: Whether installation was successful.
            message: Result message.
        """
        self.deps_progress_bar.setVisible(False)
        self.deps_progress_label.setVisible(False)
        self.install_deps_btn.setText("Install Dependencies")
        self.refresh_deps_btn.setEnabled(True)

        if success:
            self.deps_overall_label.setText(message)
            self.deps_overall_label.setStyleSheet(
                "color: green; font-weight: bold; padding: 5px;"
            )
            self.iface.messageBar().pushSuccess(
                "NASA OPERA", "Dependencies installed successfully!"
            )
            self._refresh_dependency_status()

            QMessageBox.information(
                self,
                "Dependencies Installed",
                "Dependencies have been installed successfully.\n\n"
                "If the plugin does not work immediately, "
                "please restart QGIS.",
            )
        else:
            self.deps_overall_label.setText("Installation failed.")
            self.deps_overall_label.setStyleSheet(
                "color: red; font-weight: bold; padding: 5px;"
            )
            self.install_deps_btn.setEnabled(True)

            QMessageBox.critical(
                self,
                "Installation Failed",
                f"Failed to install dependencies:\n\n{message}\n\n"
                "You can try installing manually with:\n"
                "pip install earthaccess geopandas shapely pandas",
            )

        self._deps_worker = None

    def show_dependencies_tab(self):
        """Switch to the Dependencies tab programmatically."""
        self.tab_widget.setCurrentIndex(0)

    def _create_credentials_tab(self):
        """Create the credentials settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # NASA Earthdata group
        earthdata_group = QGroupBox("NASA Earthdata Login")
        earthdata_layout = QFormLayout(earthdata_group)

        # Info label
        info_label = QLabel(
            "To access NASA OPERA data, you need a free NASA Earthdata account.\n"
            "Register at: https://urs.earthdata.nasa.gov/users/new"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 10px; padding: 5px;")
        earthdata_layout.addRow(info_label)

        # Username
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Earthdata username")
        earthdata_layout.addRow("Username:", self.username_input)

        # Password
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Earthdata password")
        earthdata_layout.addRow("Password:", self.password_input)

        # Test credentials button
        self.test_credentials_btn = QPushButton("Test Credentials")
        self.test_credentials_btn.clicked.connect(self._test_credentials)
        earthdata_layout.addRow("", self.test_credentials_btn)

        # Note about netrc
        netrc_label = QLabel(
            "Note: Credentials are stored in ~/.netrc file for earthaccess."
        )
        netrc_label.setWordWrap(True)
        netrc_label.setStyleSheet("font-size: 9px; font-style: italic;")
        earthdata_layout.addRow(netrc_label)

        layout.addWidget(earthdata_group)
        layout.addStretch()

        return widget

    def _create_display_tab(self):
        """Create the display settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Footprint style group
        style_group = QGroupBox("Footprint Style")
        style_layout = QFormLayout(style_group)

        # Fill color (simplified - just opacity)
        self.fill_opacity_spin = QSpinBox()
        self.fill_opacity_spin.setRange(0, 100)
        self.fill_opacity_spin.setValue(20)
        self.fill_opacity_spin.setSuffix("%")
        style_layout.addRow("Fill Opacity:", self.fill_opacity_spin)

        # Outline width
        self.outline_width_spin = QSpinBox()
        self.outline_width_spin.setRange(1, 10)
        self.outline_width_spin.setValue(2)
        self.outline_width_spin.setSuffix(" px")
        style_layout.addRow("Outline Width:", self.outline_width_spin)

        layout.addWidget(style_group)

        # Raster display group
        raster_group = QGroupBox("Raster Display")
        raster_layout = QFormLayout(raster_group)

        # Default colormap
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(
            [
                "viridis",
                "plasma",
                "inferno",
                "magma",
                "cividis",
                "Greys",
                "Blues",
                "Greens",
                "Oranges",
                "Reds",
                "YlOrBr",
                "YlGn",
                "BuGn",
                "PuBu",
                "RdPu",
                "terrain",
                "ocean",
                "gist_earth",
            ]
        )
        raster_layout.addRow("Default Colormap:", self.colormap_combo)

        # Auto zoom to layer
        self.auto_zoom_check = QCheckBox()
        self.auto_zoom_check.setChecked(True)
        raster_layout.addRow("Auto Zoom to Layer:", self.auto_zoom_check)

        layout.addWidget(raster_group)
        layout.addStretch()

        return widget

    def _create_advanced_tab(self):
        """Create the advanced settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Search defaults group
        search_group = QGroupBox("Search Defaults")
        search_layout = QFormLayout(search_group)

        # Default max results
        self.default_max_results_spin = QSpinBox()
        self.default_max_results_spin.setRange(10, 500)
        self.default_max_results_spin.setValue(50)
        search_layout.addRow("Default Max Results:", self.default_max_results_spin)

        # Default date range (months back)
        self.default_months_spin = QSpinBox()
        self.default_months_spin.setRange(1, 24)
        self.default_months_spin.setValue(1)
        self.default_months_spin.setSuffix(" month(s)")
        search_layout.addRow("Default Date Range:", self.default_months_spin)

        layout.addWidget(search_group)

        # Cache group
        cache_group = QGroupBox("Cache")
        cache_layout = QFormLayout(cache_group)

        # Cache directory
        cache_dir_layout = QHBoxLayout()
        self.cache_dir_input = QLineEdit()
        self.cache_dir_input.setPlaceholderText("Default cache directory")
        cache_dir_layout.addWidget(self.cache_dir_input)
        self.cache_dir_btn = QPushButton("...")
        self.cache_dir_btn.setMaximumWidth(30)
        self.cache_dir_btn.clicked.connect(self._browse_cache_dir)
        cache_dir_layout.addWidget(self.cache_dir_btn)
        cache_layout.addRow("Cache Directory:", cache_dir_layout)

        # Clear cache button
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        cache_layout.addRow("", self.clear_cache_btn)

        layout.addWidget(cache_group)

        # Debug group
        debug_group = QGroupBox("Debug")
        debug_layout = QFormLayout(debug_group)

        # Debug mode
        self.debug_check = QCheckBox()
        self.debug_check.setChecked(False)
        debug_layout.addRow("Debug Mode:", self.debug_check)

        layout.addWidget(debug_group)
        layout.addStretch()

        return widget

    def _create_ai_tab(self):
        """Create the AI Assistant settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # AI Dependencies group
        ai_deps_group = QGroupBox("AI Dependencies")
        ai_deps_layout = QVBoxLayout(ai_deps_group)

        self.ai_deps_label = QLabel("Checking AI dependencies...")
        self.ai_deps_label.setStyleSheet("font-size: 10px;")
        ai_deps_layout.addWidget(self.ai_deps_label)

        # AI progress bar (hidden by default)
        self.ai_deps_progress_bar = QProgressBar()
        self.ai_deps_progress_bar.setRange(0, 100)
        self.ai_deps_progress_bar.setVisible(False)
        ai_deps_layout.addWidget(self.ai_deps_progress_bar)

        self.ai_deps_progress_label = QLabel("")
        self.ai_deps_progress_label.setWordWrap(True)
        self.ai_deps_progress_label.setStyleSheet("font-size: 10px;")
        self.ai_deps_progress_label.setVisible(False)
        ai_deps_layout.addWidget(self.ai_deps_progress_label)

        self.install_ai_deps_btn = QPushButton("Install AI Dependencies")
        self.install_ai_deps_btn.setStyleSheet("""
            QPushButton {
                background-color: #7B1FA2;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #6A1B9A; }
            QPushButton:disabled { background-color: #BDBDBD; }
        """)
        self.install_ai_deps_btn.clicked.connect(self._install_ai_dependencies)
        ai_deps_layout.addWidget(self.install_ai_deps_btn)

        layout.addWidget(ai_deps_group)

        # Provider settings group
        provider_group = QGroupBox("LLM Provider")
        provider_layout = QFormLayout(provider_group)

        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItems(
            ["OpenAI", "Anthropic", "Amazon Bedrock", "Google Gemini", "Ollama"]
        )
        self.ai_provider_combo.currentTextChanged.connect(self._on_ai_provider_changed)
        provider_layout.addRow("Provider:", self.ai_provider_combo)

        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        provider_layout.addRow("Model:", self.ai_model_combo)

        layout.addWidget(provider_group)

        # Authentication group
        auth_group = QGroupBox("Authentication")
        auth_layout = QFormLayout(auth_group)

        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_input.setPlaceholderText("Enter API key")
        auth_layout.addRow("API Key:", self.ai_api_key_input)

        self.ai_base_url_input = QLineEdit()
        self.ai_base_url_input.setPlaceholderText("http://localhost:11434")
        self.ai_base_url_input.setVisible(False)
        self.ai_base_url_label = QLabel("Base URL:")
        self.ai_base_url_label.setVisible(False)
        auth_layout.addRow(self.ai_base_url_label, self.ai_base_url_input)

        # OAuth buttons
        oauth_layout = QHBoxLayout()
        self.ai_oauth_anthropic_btn = QPushButton("Sign in with Claude")
        self.ai_oauth_anthropic_btn.setStyleSheet("font-size: 10px; padding: 4px 8px;")
        self.ai_oauth_anthropic_btn.clicked.connect(
            lambda: self._start_oauth("anthropic")
        )
        self.ai_oauth_anthropic_btn.setVisible(False)
        oauth_layout.addWidget(self.ai_oauth_anthropic_btn)

        self.ai_oauth_openai_btn = QPushButton("Sign in with OpenAI")
        self.ai_oauth_openai_btn.setStyleSheet("font-size: 10px; padding: 4px 8px;")
        self.ai_oauth_openai_btn.clicked.connect(lambda: self._start_oauth("openai"))
        self.ai_oauth_openai_btn.setVisible(False)
        oauth_layout.addWidget(self.ai_oauth_openai_btn)

        oauth_layout.addStretch()
        auth_layout.addRow("", oauth_layout)

        # Test connection button
        self.ai_test_btn = QPushButton("Test Connection")
        self.ai_test_btn.clicked.connect(self._test_ai_connection)
        auth_layout.addRow("", self.ai_test_btn)

        layout.addWidget(auth_group)

        # Parameters group
        params_group = QGroupBox("Parameters")
        params_layout = QFormLayout(params_group)

        self.ai_temperature_spin = QSpinBox()
        self.ai_temperature_spin.setRange(0, 100)
        self.ai_temperature_spin.setValue(30)
        self.ai_temperature_spin.setSuffix("%")
        params_layout.addRow("Temperature:", self.ai_temperature_spin)

        self.ai_max_tokens_spin = QSpinBox()
        self.ai_max_tokens_spin.setRange(256, 8192)
        self.ai_max_tokens_spin.setValue(4096)
        self.ai_max_tokens_spin.setSingleStep(256)
        params_layout.addRow("Max Tokens:", self.ai_max_tokens_spin)

        layout.addWidget(params_group)

        layout.addStretch()

        # Populate models for default provider and check AI deps
        self._on_ai_provider_changed(self.ai_provider_combo.currentText())

        from qgis.PyQt.QtCore import QTimer

        QTimer.singleShot(200, self._refresh_ai_deps_status)

        return widget

    def _on_ai_provider_changed(self, provider_text):
        """Update UI when AI provider selection changes.

        Args:
            provider_text: Display name of the selected provider.
        """
        provider_map = {
            "OpenAI": "openai",
            "Anthropic": "anthropic",
            "Amazon Bedrock": "bedrock",
            "Google Gemini": "gemini",
            "Ollama": "ollama",
        }
        provider = provider_map.get(provider_text, "openai")

        # Update model list
        from ..ai.llm_client import AVAILABLE_MODELS

        self.ai_model_combo.clear()
        models = AVAILABLE_MODELS.get(provider, [])
        self.ai_model_combo.addItems(models)

        # Show/hide base URL for Ollama
        is_ollama = provider == "ollama"
        self.ai_base_url_input.setVisible(is_ollama)
        self.ai_base_url_label.setVisible(is_ollama)
        if is_ollama:
            if not self.ai_base_url_input.text():
                self.ai_base_url_input.setText("http://localhost:11434")

        # Show/hide OAuth buttons
        self.ai_oauth_anthropic_btn.setVisible(provider == "anthropic")
        self.ai_oauth_openai_btn.setVisible(provider == "openai")

        # API key not required for Ollama
        self.ai_api_key_input.setPlaceholderText(
            "Not required for local Ollama" if is_ollama else "Enter API key"
        )

    def _refresh_ai_deps_status(self):
        """Check and display AI dependency status."""
        try:
            from ..deps_manager import all_ai_dependencies_met, check_ai_dependencies

            deps = check_ai_dependencies()
            all_ok = all_ai_dependencies_met()

            status_parts = []
            for dep in deps:
                if dep["installed"]:
                    v = dep["version"] or "installed"
                    status_parts.append(f"{dep['pip_name']}: Installed ({v})")
                else:
                    status_parts.append(f"{dep['pip_name']}: Not installed")

            self.ai_deps_label.setText("\n".join(status_parts))

            if all_ok:
                self.ai_deps_label.setStyleSheet(
                    "color: green; font-size: 10px; font-weight: bold;"
                )
                self.install_ai_deps_btn.setVisible(False)
            else:
                self.ai_deps_label.setStyleSheet("color: #E65100; font-size: 10px;")
                self.install_ai_deps_btn.setVisible(True)
        except Exception as e:
            self.ai_deps_label.setText(f"Error checking dependencies: {e}")
            self.ai_deps_label.setStyleSheet("color: red; font-size: 10px;")

    def _install_ai_dependencies(self):
        """Install AI dependencies in the background."""
        from ..deps_manager import (
            DepsInstallWorker,
            get_missing_ai_packages,
            get_venv_dir,
            install_packages,
            venv_exists,
            create_venv,
            ensure_venv_packages_available,
        )

        missing = get_missing_ai_packages()
        if not missing:
            self.ai_deps_label.setText("All AI dependencies are installed.")
            self.ai_deps_label.setStyleSheet(
                "color: green; font-size: 10px; font-weight: bold;"
            )
            return

        self.install_ai_deps_btn.setEnabled(False)
        self.install_ai_deps_btn.setText("Installing...")
        self.ai_deps_progress_bar.setVisible(True)
        self.ai_deps_progress_bar.setValue(0)
        self.ai_deps_progress_label.setVisible(True)
        self.ai_deps_progress_label.setText("Starting installation...")

        # Use a simple thread for AI deps installation
        from qgis.PyQt.QtCore import QThread, pyqtSignal

        class AIInstallWorker(QThread):
            """Worker for installing AI dependencies."""

            progress = pyqtSignal(int, str)
            finished = pyqtSignal(bool, str)

            def run(self):
                """Install AI packages."""
                import time

                try:
                    start = time.time()
                    venv_dir = get_venv_dir()

                    if not venv_exists():
                        self.progress.emit(10, "Creating virtual environment...")
                        create_venv(venv_dir)

                    self.progress.emit(20, f"Installing: {', '.join(missing)}...")
                    success, msg = install_packages(venv_dir, missing)

                    if not success:
                        self.finished.emit(False, msg)
                        return

                    self.progress.emit(80, "Configuring paths...")
                    ensure_venv_packages_available()

                    elapsed = time.time() - start
                    self.progress.emit(100, f"Done in {elapsed:.1f}s")
                    self.finished.emit(
                        True, f"AI dependencies installed in {elapsed:.1f}s!"
                    )
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._ai_install_worker = AIInstallWorker()
        self._ai_install_worker.progress.connect(self._on_ai_install_progress)
        self._ai_install_worker.finished.connect(self._on_ai_install_finished)
        self._ai_install_worker.start()

    def _on_ai_install_progress(self, percent, message):
        """Handle AI install progress.

        Args:
            percent: Progress percentage.
            message: Status message.
        """
        self.ai_deps_progress_bar.setValue(percent)
        self.ai_deps_progress_label.setText(message)

    def _on_ai_install_finished(self, success, message):
        """Handle AI install completion.

        Args:
            success: Whether installation succeeded.
            message: Result message.
        """
        self.ai_deps_progress_bar.setVisible(False)
        self.ai_deps_progress_label.setVisible(False)
        self.install_ai_deps_btn.setText("Install AI Dependencies")
        self.install_ai_deps_btn.setEnabled(True)

        if success:
            self.iface.messageBar().pushSuccess("NASA OPERA", message)
            QMessageBox.information(
                self,
                "AI Dependencies Installed",
                f"{message}\n\nIf the AI Assistant does not work immediately, "
                "please restart QGIS.",
            )
        else:
            QMessageBox.critical(
                self,
                "Installation Failed",
                f"Failed to install AI dependencies:\n\n{message}",
            )
            self.install_ai_deps_btn.setEnabled(True)

        self._refresh_ai_deps_status()
        self._ai_install_worker = None

    def _start_oauth(self, provider):
        """Start OAuth flow for the given provider.

        Args:
            provider: Provider name ('anthropic' or 'openai').
        """
        try:
            from ..ai.oauth import OAuthFlow

            flow = OAuthFlow(provider)
            success, result = flow.start_flow()

            if success:
                self.ai_api_key_input.setText(result)
                QMessageBox.information(
                    self,
                    "OAuth Success",
                    f"Successfully authenticated with {provider}.\n"
                    "The token has been saved.",
                )
            else:
                QMessageBox.warning(
                    self, "OAuth Failed", f"Authentication failed:\n{result}"
                )
        except Exception as e:
            QMessageBox.critical(self, "OAuth Error", f"OAuth error:\n{str(e)}")

    def _test_ai_connection(self):
        """Test the AI provider connection."""
        try:
            from ..deps_manager import all_ai_dependencies_met

            if not all_ai_dependencies_met():
                QMessageBox.warning(
                    self,
                    "Dependencies Missing",
                    "AI dependencies are not installed.\n"
                    "Please click 'Install AI Dependencies' first.",
                )
                return
        except Exception as exc:
            # Dependency check is best-effort; fall through to existing behavior.
            print(f"NASA OPERA: AI dependency check failed: {exc}", file=sys.stderr)

        provider_map = {
            "OpenAI": "openai",
            "Anthropic": "anthropic",
            "Amazon Bedrock": "bedrock",
            "Google Gemini": "gemini",
            "Ollama": "ollama",
        }
        provider = provider_map.get(self.ai_provider_combo.currentText(), "openai")
        model = self.ai_model_combo.currentText()
        api_key = self.ai_api_key_input.text().strip()
        base_url = self.ai_base_url_input.text().strip()

        if provider != "ollama" and not api_key:
            QMessageBox.warning(self, "Missing API Key", "Please enter an API key.")
            return

        try:
            from ..ai.llm_client import LLMClient

            client = LLMClient(
                provider=provider,
                model=model,
                api_key=api_key if api_key else None,
                base_url=base_url if base_url else None,
            )
            success, message = client.validate_connection()

            if success:
                QMessageBox.information(self, "Connection Test", message)
            else:
                QMessageBox.warning(self, "Connection Test", message)
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Test failed:\n{str(e)}")

    def show_ai_tab(self):
        """Switch to the AI Assistant tab programmatically."""
        # AI tab is the 5th tab (index 4)
        self.tab_widget.setCurrentIndex(4)

    def _browse_cache_dir(self):
        """Open directory browser for cache directory."""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Cache Directory", self.cache_dir_input.text() or ""
        )
        if dir_path:
            self.cache_dir_input.setText(dir_path)

    def _test_credentials(self):
        """Test NASA Earthdata credentials."""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(
                self, "Missing Credentials", "Please enter both username and password."
            )
            return

        try:
            import earthaccess
            import os

            # Ensure environment strategy has values before first login attempt.
            os.environ["EARTHDATA_USERNAME"] = username
            os.environ["EARTHDATA_PASSWORD"] = password

            # Persist credentials so fresh installs work without extra manual setup.
            self._save_to_netrc(username, password)

            # Try environment first, then netrc as a fallback.
            auth = earthaccess.login(strategy="environment")
            if not auth:
                auth = earthaccess.login(strategy="netrc")

            if auth:
                QMessageBox.information(
                    self,
                    "Success",
                    "Successfully authenticated with NASA Earthdata! Credentials were saved to ~/.netrc.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Authentication Failed",
                    "Could not authenticate. Please check your credentials.",
                )
        except ImportError:
            QMessageBox.critical(
                self,
                "Error",
                "earthaccess package is not installed.\n"
                "Please install it with: pip install earthaccess",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Authentication failed:\n{str(e)}")

    def _clear_cache(self):
        """Clear the cache directory."""
        cache_dir = self.cache_dir_input.text().strip()
        if not cache_dir:
            QMessageBox.information(self, "No Cache", "No cache directory configured.")
            return

        reply = QMessageBox.question(
            self,
            "Clear Cache",
            f"Are you sure you want to clear the cache?\n{cache_dir}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            import os

            try:
                if os.path.exists(cache_dir):
                    shutil.rmtree(cache_dir)
                    os.makedirs(cache_dir)
                    QMessageBox.information(
                        self, "Cache Cleared", "Cache directory has been cleared."
                    )
                else:
                    QMessageBox.information(
                        self, "No Cache", "Cache directory does not exist."
                    )
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear cache:\n{str(e)}")

    def _load_settings(self):
        """Load settings from QSettings."""
        # Credentials (note: actual credentials should be in .netrc)
        self.username_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}username", "", type=str)
        )
        # Don't load password for security

        # Display
        self.fill_opacity_spin.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}fill_opacity", 20, type=int)
        )
        self.outline_width_spin.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}outline_width", 2, type=int)
        )
        colormap_index = self.colormap_combo.findText(
            self.settings.value(f"{self.SETTINGS_PREFIX}colormap", "viridis", type=str)
        )
        if colormap_index >= 0:
            self.colormap_combo.setCurrentIndex(colormap_index)
        self.auto_zoom_check.setChecked(
            self.settings.value(f"{self.SETTINGS_PREFIX}auto_zoom", True, type=bool)
        )

        # Advanced
        self.default_max_results_spin.setValue(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}default_max_results", 50, type=int
            )
        )
        self.default_months_spin.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}default_months", 1, type=int)
        )
        self.cache_dir_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}cache_dir", "", type=str)
        )
        self.debug_check.setChecked(
            self.settings.value(f"{self.SETTINGS_PREFIX}debug", False, type=bool)
        )

        # AI settings
        ai_provider = self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_provider", "OpenAI", type=str
        )
        ai_provider_index = self.ai_provider_combo.findText(ai_provider)
        if ai_provider_index >= 0:
            self.ai_provider_combo.setCurrentIndex(ai_provider_index)

        ai_model = self.settings.value(f"{self.SETTINGS_PREFIX}ai_model", "", type=str)
        if ai_model:
            model_index = self.ai_model_combo.findText(ai_model)
            if model_index >= 0:
                self.ai_model_combo.setCurrentIndex(model_index)
            else:
                self.ai_model_combo.setEditText(ai_model)

        self.ai_api_key_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}ai_api_key", "", type=str)
        )
        self.ai_base_url_input.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}ai_base_url", "", type=str)
        )
        self.ai_temperature_spin.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}ai_temperature", 30, type=int)
        )
        self.ai_max_tokens_spin.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}ai_max_tokens", 4096, type=int)
        )

        self.status_label.setText("Settings loaded")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")

    def _save_settings(self):
        """Save settings to QSettings."""
        # Credentials
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}username", self.username_input.text()
        )
        # Save password to netrc instead of QSettings for security
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        if username and password:
            self._save_to_netrc(username, password)

        # Display
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}fill_opacity", self.fill_opacity_spin.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}outline_width", self.outline_width_spin.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}colormap", self.colormap_combo.currentText()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}auto_zoom", self.auto_zoom_check.isChecked()
        )

        # Advanced
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}default_max_results",
            self.default_max_results_spin.value(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}default_months", self.default_months_spin.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}cache_dir", self.cache_dir_input.text()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}debug", self.debug_check.isChecked()
        )

        # AI settings
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_provider",
            self.ai_provider_combo.currentText(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_model",
            self.ai_model_combo.currentText(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_api_key",
            self.ai_api_key_input.text(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_base_url",
            self.ai_base_url_input.text(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_temperature",
            self.ai_temperature_spin.value(),
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_max_tokens",
            self.ai_max_tokens_spin.value(),
        )

        self.settings.sync()

        self.status_label.setText("Settings saved")
        self.status_label.setStyleSheet("color: green; font-size: 10px;")

        self.iface.messageBar().pushSuccess(
            "NASA OPERA", "Settings saved successfully!"
        )

    def _save_to_netrc(self, username, password):
        """Save credentials to .netrc file for earthaccess."""
        import os
        from pathlib import Path

        netrc_path = Path.home() / ".netrc"

        try:
            # Read existing content
            existing_lines = []
            if netrc_path.exists():
                with open(netrc_path, "r") as f:
                    existing_lines = f.readlines()

            # Remove existing earthdata entry
            new_lines = []
            skip_machine = False
            for line in existing_lines:
                if line.strip().startswith("machine urs.earthdata.nasa.gov"):
                    skip_machine = True
                    continue
                if (
                    skip_machine
                    and line.strip()
                    and not line.strip().startswith("machine")
                ):
                    continue
                skip_machine = False
                new_lines.append(line)

            # Add new entry
            new_lines.append(
                f"\nmachine urs.earthdata.nasa.gov login {username} password {password}\n"
            )

            # Write file
            with open(netrc_path, "w") as f:
                f.writelines(new_lines)

            # Set permissions (Unix-like systems)
            if os.name != "nt":
                os.chmod(netrc_path, 0o600)

        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Could not save credentials to .netrc:\n{str(e)}\n\n"
                "You may need to configure your Earthdata credentials manually.",
            )

    def _reset_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Credentials - don't reset
        # self.username_input.clear()
        # self.password_input.clear()

        # Display
        self.fill_opacity_spin.setValue(20)
        self.outline_width_spin.setValue(2)
        self.colormap_combo.setCurrentIndex(0)
        self.auto_zoom_check.setChecked(True)

        # Advanced
        self.default_max_results_spin.setValue(50)
        self.default_months_spin.setValue(1)
        self.cache_dir_input.clear()
        self.debug_check.setChecked(False)

        # AI settings - don't reset API keys
        self.ai_provider_combo.setCurrentIndex(0)
        self.ai_temperature_spin.setValue(30)
        self.ai_max_tokens_spin.setValue(4096)
        self.ai_base_url_input.clear()

        self.status_label.setText("Defaults restored (not saved)")
        self.status_label.setStyleSheet("color: orange; font-size: 10px;")
