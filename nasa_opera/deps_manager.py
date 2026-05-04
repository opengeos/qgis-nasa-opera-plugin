"""
Dependency checks for NASA OPERA Plugin.

The plugin no longer installs Python packages itself. It still checks whether
the required packages are importable and, for users upgrading from older
versions, adds the legacy plugin virtual environment to ``sys.path`` when it
already exists.
"""

import importlib
import os
import sys
from typing import Dict, List, Optional

# Required packages: (import_name, pip_install_name)
REQUIRED_PACKAGES = [
    ("earthaccess", "earthaccess"),
    ("geopandas", "geopandas"),
    ("shapely", "shapely"),
    ("pandas", "pandas"),
]

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".qgis_nasa_opera")
PYTHON_VERSION = f"py{sys.version_info.major}.{sys.version_info.minor}"


def get_venv_dir() -> str:
    """Return the legacy plugin virtual environment directory."""
    return os.path.join(CACHE_DIR, f"venv_{PYTHON_VERSION}")


def get_venv_python_path(venv_dir: Optional[str] = None) -> str:
    """Return the Python executable path inside the legacy venv."""
    if venv_dir is None:
        venv_dir = get_venv_dir()
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python3")


def get_venv_site_packages(venv_dir: Optional[str] = None) -> str:
    """Return the site-packages path inside the legacy venv."""
    if venv_dir is None:
        venv_dir = get_venv_dir()
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Lib", "site-packages")

    lib_dir = os.path.join(venv_dir, "lib")
    if os.path.isdir(lib_dir):
        for entry in sorted(os.listdir(lib_dir)):
            if entry.startswith("python"):
                candidate = os.path.join(lib_dir, entry, "site-packages")
                if os.path.isdir(candidate):
                    return candidate

    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return os.path.join(venv_dir, "lib", py_ver, "site-packages")


def venv_exists() -> bool:
    """Return True when the legacy plugin venv exists."""
    venv_dir = get_venv_dir()
    python_path = get_venv_python_path(venv_dir)
    return os.path.isdir(venv_dir) and os.path.isfile(python_path)


def ensure_venv_packages_available() -> bool:
    """Add legacy venv site-packages to ``sys.path`` when present."""
    if not venv_exists():
        return False

    site_packages = get_venv_site_packages()
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    return True


def check_dependencies() -> List[Dict]:
    """Check whether required Python packages are importable."""
    results = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        info: Dict = {
            "name": import_name,
            "pip_name": pip_name,
            "installed": False,
            "version": None,
        }
        try:
            mod = importlib.import_module(import_name)
            info["installed"] = True
            info["version"] = getattr(mod, "__version__", "installed")
        except ImportError:
            pass
        results.append(info)
    return results


def all_dependencies_met() -> bool:
    """Return True if all required packages are importable."""
    return all(dep["installed"] for dep in check_dependencies())


def get_missing_packages() -> List[str]:
    """Return pip install names for missing packages."""
    return [dep["pip_name"] for dep in check_dependencies() if not dep["installed"]]
