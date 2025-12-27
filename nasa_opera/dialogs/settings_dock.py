"""
Settings Dock Widget for NASA OPERA Plugin

This module provides a settings panel for configuring the NASA OPERA plugin,
including Earthdata credentials and display options.
"""

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

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

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
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet("color: #1565C0; padding: 5px;")
        layout.addWidget(header_label)

        # Tab widget for organized settings
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # Credentials tab
        credentials_tab = self._create_credentials_tab()
        tab_widget.addTab(credentials_tab, "Credentials")

        # Display settings tab
        display_tab = self._create_display_tab()
        tab_widget.addTab(display_tab, "Display")

        # Advanced settings tab
        advanced_tab = self._create_advanced_tab()
        tab_widget.addTab(advanced_tab, "Advanced")

        # Buttons
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet(
            """
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
        """
        )
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
        info_label.setStyleSheet("color: #666; font-size: 10px; padding: 5px;")
        earthdata_layout.addRow(info_label)

        # Username
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Earthdata username")
        earthdata_layout.addRow("Username:", self.username_input)

        # Password
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
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
        netrc_label.setStyleSheet("color: #888; font-size: 9px; font-style: italic;")
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

            # Try to authenticate
            auth = earthaccess.login(strategy="environment")
            if auth:
                QMessageBox.information(
                    self, "Success", "Successfully authenticated with NASA Earthdata!"
                )
            else:
                # Try with provided credentials
                import os

                os.environ["EARTHDATA_USERNAME"] = username
                os.environ["EARTHDATA_PASSWORD"] = password

                auth = earthaccess.login(strategy="environment")
                if auth:
                    QMessageBox.information(
                        self,
                        "Success",
                        "Successfully authenticated with NASA Earthdata!",
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
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
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
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
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

        self.status_label.setText("Defaults restored (not saved)")
        self.status_label.setStyleSheet("color: orange; font-size: 10px;")
