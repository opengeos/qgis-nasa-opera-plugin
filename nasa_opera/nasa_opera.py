"""
NASA OPERA QGIS Plugin - Main Plugin Class

This module contains the main plugin class that manages the QGIS interface
integration, menu items, toolbar buttons, and dockable panels.
"""

import os
import sys

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar, QMessageBox

OPEN_GEOAGENT_PLUGIN_CANDIDATES = ("open_geoagent",)


TOOLBAR_OBJECT_NAME = "NasaOperaToolbar"
MENU_TITLE = "&NASA OPERA"

class NasaOpera:
    """NASA OPERA implementation class for QGIS."""

    def __init__(self, iface):
        """Constructor.

        Args:
            iface: An interface instance that provides the hook to QGIS.
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = None
        self.toolbar = None

        # Dock widgets (lazy loaded)
        self._opera_dock = None
        self._settings_dock = None

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        checkable=False,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        Args:
            icon_path: Path to the icon for this action.
            text: Text that appears in the menu for this action.
            callback: Function to be called when the action is triggered.
            enabled_flag: A flag indicating if the action should be enabled.
            add_to_menu: Flag indicating whether action should be added to menu.
            add_to_toolbar: Flag indicating whether action should be added to toolbar.
            status_tip: Optional text to show in status bar when mouse hovers over action.
            checkable: Whether the action is checkable (toggle).
            parent: Parent widget for the new action.

        Returns:
            The action that was created.
        """
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        action.setCheckable(checkable)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.menu.addAction(action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        self._remove_toolbars_by_object_name()
        self._remove_menus_by_title()
        # Create menu
        self.menu = QMenu("&NASA OPERA")
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        # Create toolbar
        self.toolbar = QToolBar("NASA OPERA Toolbar")
        self.toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        self.iface.addToolBar(self.toolbar)

        # Get icon paths
        icon_base = os.path.join(self.plugin_dir, "icons")

        # Main panel icon - use custom icon or fallback to QGIS default
        main_icon = os.path.join(icon_base, "opera.svg")
        if not os.path.exists(main_icon):
            main_icon = ":/images/themes/default/mActionAddRasterLayer.svg"

        settings_icon = os.path.join(icon_base, "settings.svg")
        if not os.path.exists(settings_icon):
            settings_icon = ":/images/themes/default/mActionOptions.svg"

        about_icon = os.path.join(icon_base, "about.svg")
        if not os.path.exists(about_icon):
            about_icon = ":/images/themes/default/mActionHelpContents.svg"

        # Add NASA OPERA Panel action (checkable for dock toggle)
        self.opera_action = self.add_action(
            main_icon,
            "NASA OPERA Search",
            self.toggle_opera_dock,
            status_tip="Toggle NASA OPERA Search Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Add AI Assistant action. The chat UI is owned by OpenGeoAgent.
        ai_icon = os.path.join(icon_base, "ai_chat.svg")
        if not os.path.exists(ai_icon):
            ai_icon = ":/images/themes/default/mActionHelpContents.svg"

        self.ai_chat_action = self.add_action(
            ai_icon,
            "AI Assistant",
            self.open_ai_assistant,
            status_tip="Open the OpenGeoAgent chat panel",
            parent=self.iface.mainWindow(),
        )

        # Add Settings Panel action (checkable for dock toggle)
        self.settings_action = self.add_action(
            settings_icon,
            "Settings",
            self.toggle_settings_dock,
            status_tip="Toggle Settings Panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Add separator to menu
        self.menu.addSeparator()

        # Update icon - use QGIS default download/update icon
        update_icon = ":/images/themes/default/mActionRefresh.svg"

        # Add Check for Updates action (menu only)
        self.add_action(
            update_icon,
            "Check for Updates...",
            self.show_update_checker,
            add_to_toolbar=False,
            status_tip="Check for plugin updates from GitHub",
            parent=self.iface.mainWindow(),
        )

        # Add About action (menu only)
        self.add_action(
            about_icon,
            "About NASA OPERA Plugin",
            self.show_about,
            add_to_toolbar=False,
            status_tip="About NASA OPERA Plugin",
            parent=self.iface.mainWindow(),
        )


    def _remove_toolbar(self, toolbar):
        """Detach and schedule deletion of a plugin toolbar widget."""
        if toolbar is None:
            return

        main_window = self.iface.mainWindow()
        actions = []
        try:
            actions = list(toolbar.actions())
        except Exception:
            pass  # nosec B110
        try:
            toolbar.clear()
        except Exception:
            pass  # nosec B110
        for action in actions:
            try:
                action.deleteLater()
            except Exception:
                pass  # nosec B110
        try:
            main_window.removeToolBar(toolbar)
        except Exception:
            pass  # nosec B110
        try:
            toolbar.hide()
        except Exception:
            pass  # nosec B110
        try:
            toolbar.setParent(None)
        except Exception:
            pass  # nosec B110
        try:
            toolbar.deleteLater()
        except Exception:
            pass  # nosec B110

    def _remove_toolbars_by_object_name(self):
        """Remove current or stale plugin toolbars from QGIS."""
        main_window = self.iface.mainWindow()
        for toolbar in main_window.findChildren(QToolBar, TOOLBAR_OBJECT_NAME):
            self._remove_toolbar(toolbar)

    def _plugin_menu_titles(self):
        """Return possible translated and untranslated plugin menu titles."""
        titles = {MENU_TITLE}
        translator = getattr(self, "tr", None)
        if callable(translator):
            try:
                titles.add(translator(MENU_TITLE))
            except Exception:
                pass  # nosec B110
        return titles

    def _remove_menu(self, menu):
        """Detach and schedule deletion of a plugin menu."""
        if menu is None:
            return

        main_window = self.iface.mainWindow()
        try:
            menu.clear()
        except Exception:
            pass  # nosec B110
        try:
            main_window.menuBar().removeAction(menu.menuAction())
        except Exception:
            pass  # nosec B110
        try:
            menu.setParent(None)
        except Exception:
            pass  # nosec B110
        try:
            menu.deleteLater()
        except Exception:
            pass  # nosec B110

    def _remove_menus_by_title(self):
        """Remove current or stale plugin menus from QGIS."""
        menu_bar = self.iface.mainWindow().menuBar()
        titles = self._plugin_menu_titles()
        for action in menu_bar.actions():
            menu = action.menu()
            if menu is not None and menu.title() in titles:
                self._remove_menu(menu)

    def unload(self):
        """Remove the plugin menu item and icon from QGIS GUI."""
        # Remove dock widgets
        if self._opera_dock:
            self.iface.removeDockWidget(self._opera_dock)
            self._opera_dock.deleteLater()
            self._opera_dock = None

        if self._settings_dock:
            self.iface.removeDockWidget(self._settings_dock)
            self._settings_dock.deleteLater()
            self._settings_dock = None

        # Remove actions from menu
        for action in self.actions:
            self.iface.removePluginMenu("&NASA OPERA", action)

        # Remove toolbar
        if self.toolbar:
            del self.toolbar

        # Remove menu
        if self.menu:
            self.menu.deleteLater()

        self._remove_toolbars_by_object_name()
        self._remove_menus_by_title()

    def toggle_opera_dock(self):
        """Toggle the NASA OPERA dock widget visibility."""
        if self._opera_dock is None:
            # Check dependencies before creating the search panel
            try:
                from .deps_manager import all_dependencies_met, get_missing_packages

                if not all_dependencies_met():
                    missing = ", ".join(get_missing_packages())
                    box = QMessageBox(self.iface.mainWindow())
                    box.setIcon(QMessageBox.Icon.Warning)
                    box.setWindowTitle("Missing Dependencies")
                    box.setText(
                        "The NASA OPERA plugin requires additional Python "
                        "packages that are not installed.\n\n"
                        f"Missing packages: {missing}\n\n"
                        "Open Settings > Dependencies to install them in an "
                        "isolated plugin environment."
                    )
                    install_button = box.addButton(
                        "Install Dependencies", QMessageBox.ButtonRole.ActionRole
                    )
                    box.addButton(QMessageBox.StandardButton.Ok)
                    box.exec()
                    if box.clickedButton() == install_button:
                        self.show_dependencies_settings()
                    self.opera_action.setChecked(False)
                    return
            except Exception as exc:
                # Dependency check is best-effort; fall through to existing behavior.
                print(f"NASA OPERA: dependency check failed: {exc}", file=sys.stderr)

            try:
                from .dialogs.opera_dock import OperaDockWidget

                self._opera_dock = OperaDockWidget(self.iface, self.iface.mainWindow())
                self._opera_dock.setObjectName("NasaOperaDock")
                self._opera_dock.visibilityChanged.connect(
                    self._on_opera_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._opera_dock
                )
                self._opera_dock.show()
                self._opera_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create NASA OPERA panel:\n{str(e)}",
                )
                self.opera_action.setChecked(False)
                return

        # Toggle visibility
        if self._opera_dock.isVisible():
            self._opera_dock.hide()
        else:
            self._opera_dock.show()
            self._opera_dock.raise_()

    def _on_opera_visibility_changed(self, visible):
        """Handle Opera dock visibility change."""
        self.opera_action.setChecked(visible)

    def open_ai_assistant(self):
        """Open the OpenGeoAgent chat panel, or prompt for plugin installation."""
        plugin = self._get_open_geoagent_plugin()
        if plugin is None:
            self._prompt_open_geoagent_install()
            return

        if not hasattr(plugin, "toggle_chat_dock"):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "OpenGeoAgent Required",
                "OpenGeoAgent is installed, but this version does not expose "
                "the chat panel launcher expected by NASA OPERA.\n\n"
                "Please update OpenGeoAgent and try again.",
            )
            return

        try:
            chat_dock = getattr(plugin, "_chat_dock", None)
            if chat_dock is not None and chat_dock.isVisible():
                chat_dock.show()
                chat_dock.raise_()
                return

            plugin.toggle_chat_dock()
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "OpenGeoAgent",
                f"Failed to open the OpenGeoAgent chat panel:\n{exc}",
            )

    def _get_open_geoagent_plugin(self):
        """Return the loaded OpenGeoAgent plugin instance, loading it if possible."""
        try:
            import qgis.utils as qgis_utils
        except Exception as exc:
            print(f"NASA OPERA: could not import qgis.utils: {exc}", file=sys.stderr)
            return None

        plugins = getattr(qgis_utils, "plugins", {}) or {}
        for package_name in OPEN_GEOAGENT_PLUGIN_CANDIDATES:
            plugin = plugins.get(package_name)
            if plugin is not None:
                return plugin

        available = set(getattr(qgis_utils, "available_plugins", []) or [])
        for package_name in OPEN_GEOAGENT_PLUGIN_CANDIDATES:
            if package_name not in available:
                continue

            try:
                load_plugin = getattr(qgis_utils, "loadPlugin", None)
                if callable(load_plugin) and package_name not in plugins:
                    load_plugin(package_name)

                start_plugin = getattr(qgis_utils, "startPlugin", None)
                active_plugins = getattr(qgis_utils, "active_plugins", []) or []
                if callable(start_plugin) and package_name not in active_plugins:
                    start_plugin(package_name)

                plugins = getattr(qgis_utils, "plugins", {}) or {}
                plugin = plugins.get(package_name)
                if plugin is not None:
                    return plugin
            except Exception as exc:
                print(
                    f"NASA OPERA: failed to load OpenGeoAgent plugin "
                    f"'{package_name}': {exc}",
                    file=sys.stderr,
                )

        return None

    def _prompt_open_geoagent_install(self):
        """Tell the user how to install OpenGeoAgent from the QGIS Plugin Manager."""
        message = (
            "The AI Assistant is provided by the OpenGeoAgent QGIS plugin.\n\n"
            "Install it from the QGIS Plugin Manager:\n"
            "  Plugins > Manage and Install Plugins... > All\n"
            "  Search for 'OpenGeoAgent' and click Install Plugin.\n\n"
            "After installing (or enabling) OpenGeoAgent, click the AI "
            "Assistant button again."
        )
        box = QMessageBox(self.iface.mainWindow())
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Install OpenGeoAgent")
        box.setText(message)
        manager_button = box.addButton(
            "Open Plugin Manager", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()

        if box.clickedButton() == manager_button:
            self._open_qgis_plugin_manager()

    def _open_qgis_plugin_manager(self):
        """Open the QGIS Plugin Manager dialog."""
        try:
            action = self.iface.actionManagePlugins()
            if action is not None:
                action.trigger()
                return
        except Exception as exc:
            print(
                f"NASA OPERA: could not open QGIS Plugin Manager: {exc}",
                file=sys.stderr,
            )

        QMessageBox.information(
            self.iface.mainWindow(),
            "Open Plugin Manager",
            "Open the QGIS Plugin Manager from the menu:\n"
            "Plugins > Manage and Install Plugins...",
        )

    def toggle_settings_dock(self):
        """Toggle the Settings dock widget visibility."""
        if self._settings_dock is None:
            try:
                from .dialogs.settings_dock import SettingsDockWidget

                self._settings_dock = SettingsDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._settings_dock.setObjectName("NasaOperaSettingsDock")
                self._settings_dock.visibilityChanged.connect(
                    self._on_settings_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._settings_dock
                )
                self._settings_dock.show()
                self._settings_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}",
                )
                self.settings_action.setChecked(False)
                return

        # Toggle visibility
        if self._settings_dock.isVisible():
            self._settings_dock.hide()
        else:
            self._settings_dock.show()
            self._settings_dock.raise_()

    def _on_settings_visibility_changed(self, visible):
        """Handle Settings dock visibility change."""
        self.settings_action.setChecked(visible)

    def show_dependencies_settings(self):
        """Open the settings dock on the dependency installer tab."""
        if self._settings_dock is None:
            self.toggle_settings_dock()

        if self._settings_dock is not None:
            if not self._settings_dock.isVisible():
                self._settings_dock.show()
            self._settings_dock.raise_()
            self.settings_action.setChecked(True)
            show_dependencies_tab = getattr(
                self._settings_dock, "show_dependencies_tab", None
            )
            if callable(show_dependencies_tab):
                show_dependencies_tab()

    def show_about(self):
        """Display the about dialog."""
        # Read version from metadata.txt
        version = "Unknown"
        try:
            metadata_path = os.path.join(self.plugin_dir, "metadata.txt")
            with open(metadata_path, "r", encoding="utf-8") as f:
                import re

                content = f.read()
                version_match = re.search(r"^version=(.+)$", content, re.MULTILINE)
                if version_match:
                    version = version_match.group(1).strip()
        except Exception as e:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "NASA OPERA",
                f"Could not read version from metadata.txt:\n{str(e)}",
            )

        about_text = f"""
<h2>NASA OPERA Plugin for QGIS</h2>
<p>Version: {version}</p>
<p>Author: Qiusheng Wu</p>

<h3>About NASA OPERA:</h3>
<p>OPERA (Observational Products for End-Users from Remote Sensing Analysis)
is a NASA project that provides analysis-ready data products derived from
satellite observations.</p>

<h3>Available Datasets:</h3>
<ul>
<li><b>DSWX-HLS:</b> Dynamic Surface Water Extent from Harmonized Landsat Sentinel-2</li>
<li><b>DSWX-S1:</b> Dynamic Surface Water Extent from Sentinel-1</li>
<li><b>DIST-ALERT-HLS:</b> Land Surface Disturbance Alert</li>
<li><b>DIST-ANN-HLS:</b> Land Surface Disturbance Annual</li>
<li><b>RTC-S1:</b> Radiometric Terrain Corrected SAR Backscatter</li>
<li><b>CSLC-S1:</b> Coregistered Single-Look Complex</li>
</ul>

<h3>Features:</h3>
<ul>
<li><b>Search:</b> Search NASA OPERA products by location and date</li>
<li><b>Visualization:</b> Display footprints and raster data directly in QGIS</li>
<li><b>Update Checker:</b> Check for plugin updates from GitHub</li>
</ul>

<h3>Links:</h3>
<ul>
<li><a href="https://github.com/opengeos/qgis-nasa-opera-plugin">GitHub Repository</a></li>
<li><a href="https://github.com/opengeos/qgis-nasa-opera-plugin/issues">Report Issues</a></li>
<li><a href="https://www.jpl.nasa.gov/go/opera">NASA OPERA Project</a></li>
</ul>

<p>Licensed under MIT License</p>
"""
        QMessageBox.about(
            self.iface.mainWindow(),
            "About NASA OPERA Plugin",
            about_text,
        )

    def show_update_checker(self):
        """Display the update checker dialog."""
        try:
            from .dialogs.update_checker import UpdateCheckerDialog
        except ImportError as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to import update checker dialog:\n{str(e)}",
            )
            return

        try:
            dialog = UpdateCheckerDialog(self.plugin_dir, self.iface.mainWindow())
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to open update checker:\n{str(e)}",
            )
