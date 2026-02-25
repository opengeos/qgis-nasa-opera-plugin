"""
NASA OPERA QGIS Plugin

A QGIS plugin for searching and visualizing NASA OPERA (Observational Products
for End-Users from Remote Sensing Analysis) data.

This plugin provides:
- Search interface for NASA OPERA datasets
- Visualization of search results footprints
- Display of OPERA raster data layers in QGIS
"""

from .deps_manager import ensure_venv_packages_available

# Add venv site-packages to sys.path so plugin dependencies are importable.
# This is a no-op if the venv has not been created yet.
ensure_venv_packages_available()

from .nasa_opera import NasaOpera


def classFactory(iface):
    """Load NasaOpera class from file nasa_opera.

    Args:
        iface: A QGIS interface instance.

    Returns:
        NasaOpera: The plugin instance.
    """
    return NasaOpera(iface)
