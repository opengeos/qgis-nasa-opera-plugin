"""
Dependency Manager for NASA OPERA Plugin

Manages a virtual environment for plugin dependencies (earthaccess, geopandas,
shapely, pandas) to avoid polluting the QGIS built-in Python environment.

The venv is created at ~/.qgis_nasa_opera/venv_pyX.Y and its site-packages
directory is added to sys.path at runtime.
"""

import importlib
import os
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QThread, pyqtSignal

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
    """Get the path to the plugin's virtual environment directory.

    Returns:
        Path to the venv directory (~/.qgis_nasa_opera/venv_pyX.Y).
    """
    return os.path.join(CACHE_DIR, f"venv_{PYTHON_VERSION}")


def get_venv_python_path(venv_dir: Optional[str] = None) -> str:
    """Get the path to the Python executable inside the venv.

    Args:
        venv_dir: Path to the venv directory. Defaults to get_venv_dir().

    Returns:
        Path to the venv's Python executable.
    """
    if venv_dir is None:
        venv_dir = get_venv_dir()
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python3")


def get_venv_site_packages(venv_dir: Optional[str] = None) -> str:
    """Get the path to the venv's site-packages directory.

    Args:
        venv_dir: Path to the venv directory. Defaults to get_venv_dir().

    Returns:
        Path to the venv's site-packages directory.
    """
    if venv_dir is None:
        venv_dir = get_venv_dir()
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Lib", "site-packages")

    # On Unix, detect the actual Python version directory
    lib_dir = os.path.join(venv_dir, "lib")
    if os.path.isdir(lib_dir):
        for entry in sorted(os.listdir(lib_dir)):
            if entry.startswith("python"):
                candidate = os.path.join(lib_dir, entry, "site-packages")
                if os.path.isdir(candidate):
                    return candidate

    # Fallback using current Python version
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return os.path.join(venv_dir, "lib", py_ver, "site-packages")


def venv_exists() -> bool:
    """Check if the plugin's virtual environment exists and has a Python executable.

    Returns:
        True if the venv directory and Python executable exist.
    """
    venv_dir = get_venv_dir()
    python_path = get_venv_python_path(venv_dir)
    return os.path.isdir(venv_dir) and os.path.isfile(python_path)


def ensure_venv_packages_available() -> bool:
    """Add the venv's site-packages to sys.path if the venv exists.

    This is safe to call multiple times (idempotent). If the venv does not
    exist yet, this is a no-op.

    Returns:
        True if site-packages was added or already present, False if venv
        does not exist.
    """
    if not venv_exists():
        return False

    site_packages = get_venv_site_packages()
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    return True


def check_dependencies() -> List[Dict]:
    """Check if required Python packages are importable.

    Returns:
        List of dicts with keys: name, pip_name, installed, version.
    """
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
    """Return True if all required packages are importable.

    Returns:
        True if all dependencies are installed and importable.
    """
    return all(dep["installed"] for dep in check_dependencies())


def get_missing_packages() -> List[str]:
    """Return pip install names of missing packages.

    Returns:
        List of pip package names that are not currently importable.
    """
    return [dep["pip_name"] for dep in check_dependencies() if not dep["installed"]]


def _get_clean_env() -> dict:
    """Get a clean copy of the environment for subprocess calls.

    Removes variables that could interfere with venv creation and pip installs.

    Returns:
        A copy of os.environ with problematic variables removed.
    """
    env = os.environ.copy()
    for var in [
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "QGIS_PREFIX_PATH",
        "QGIS_PLUGINPATH",
    ]:
        env.pop(var, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _get_subprocess_kwargs() -> dict:
    """Get platform-specific subprocess keyword arguments.

    Returns:
        Dict of kwargs to pass to subprocess.run().
    """
    kwargs: dict = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _create_venv_with_env_builder(venv_dir: str) -> bool:
    """Attempt to create a virtual environment using venv.EnvBuilder (in-process).

    This avoids subprocess issues that occur with QGIS's embedded Python on
    Windows, where ``python -m venv`` may create the directory structure but
    fail to place the Python executable.

    Args:
        venv_dir: Path where the venv should be created.

    Returns:
        True if the venv was created and the Python executable exists.
    """
    try:
        import venv as venv_mod

        builder = venv_mod.EnvBuilder(with_pip=True)
        builder.create(venv_dir)
        return os.path.isfile(get_venv_python_path(venv_dir))
    except Exception:
        return False


def _try_copy_python_executable(venv_dir: str) -> bool:
    """Copy the current Python executable into the venv as a recovery step.

    This handles the case where venv creation produced the directory structure
    but did not place the Python executable (known to happen with QGIS's
    embedded Python on Windows).

    Args:
        venv_dir: Path to the venv directory.

    Returns:
        True if the Python executable now exists at the expected path.
    """
    python_path = get_venv_python_path(venv_dir)
    if os.path.isfile(python_path):
        return True

    target_dir = os.path.dirname(python_path)
    os.makedirs(target_dir, exist_ok=True)

    try:
        shutil.copy2(sys.executable, python_path)
        return os.path.isfile(python_path)
    except (OSError, shutil.SameFileError):
        return False


def _cleanup_partial_venv(venv_dir: str) -> None:
    """Remove a partially created venv directory (best-effort).

    Args:
        venv_dir: Path to the venv directory to clean up.
    """
    if os.path.isdir(venv_dir):
        try:
            shutil.rmtree(venv_dir)
        except OSError:
            pass


def _verify_pip_and_return(python_path: str) -> str:
    """Ensure pip is available in the venv and return the python path.

    Args:
        python_path: Path to the venv's Python executable.

    Returns:
        The *python_path* if pip is verified.

    Raises:
        RuntimeError: If pip cannot be made available.
    """
    env = _get_clean_env()
    kwargs = _get_subprocess_kwargs()

    # Try ensurepip (may already be present from EnvBuilder)
    subprocess.run(
        [python_path, "-m", "ensurepip", "--upgrade"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        **kwargs,
    )

    # Verify pip works
    result = subprocess.run(
        [python_path, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        **kwargs,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pip is not available in the virtual environment.\n"
            f"Python path: {python_path}\n"
            f"Error: {result.stderr or result.stdout}"
        )

    return python_path


def create_venv(venv_dir: str) -> str:
    """Create a virtual environment at the specified path.

    Uses a multi-strategy approach to handle embedded Python environments
    (e.g. QGIS on Windows) where the standard subprocess-based venv creation
    may fail to place the Python executable.

    Strategy order:
        1. In-process ``venv.EnvBuilder`` (most reliable for embedded Python).
        2. Subprocess ``sys.executable -m venv`` (standard approach).
        3. Recovery: copy ``sys.executable`` into the venv when the directory
           was created but the executable is missing.

    Args:
        venv_dir: Path where the venv should be created.

    Returns:
        Path to the Python executable inside the newly created venv.

    Raises:
        RuntimeError: If venv creation fails after all strategies.
    """
    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)

    python_path = get_venv_python_path(venv_dir)

    # Strategy 1: In-process EnvBuilder (avoids subprocess issues)
    if _create_venv_with_env_builder(venv_dir):
        return _verify_pip_and_return(python_path)

    # Clean up partial venv before retrying
    _cleanup_partial_venv(venv_dir)

    # Strategy 2: Subprocess approach (original method)
    env = _get_clean_env()
    kwargs = _get_subprocess_kwargs()
    subprocess_error = ""

    cmd = [sys.executable, "-m", "venv", venv_dir]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        **kwargs,
    )

    if result.returncode == 0 and os.path.isfile(python_path):
        return _verify_pip_and_return(python_path)

    if result.returncode != 0:
        subprocess_error = result.stderr or result.stdout or ""

    # Strategy 3: Recovery — venv dir exists but executable is missing
    if os.path.isdir(venv_dir) and _try_copy_python_executable(venv_dir):
        return _verify_pip_and_return(python_path)

    # All strategies failed
    details = [
        f"Python executable: {sys.executable}",
        f"Target venv: {venv_dir}",
        f"Expected python: {python_path}",
        f"Platform: {sys.platform}",
    ]
    if subprocess_error:
        details.append(f"Subprocess error: {subprocess_error}")

    raise RuntimeError(
        "Failed to create virtual environment after trying multiple strategies.\n\n"
        "This can happen when QGIS bundles Python in a way that prevents\n"
        "standard venv creation.\n\n"
        "You can try installing manually with:\n"
        "  pip install earthaccess geopandas shapely pandas\n\n"
        "Details:\n" + "\n".join(f"  {d}" for d in details)
    )


def install_packages(
    venv_dir: str,
    packages: List[str],
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[bool, str]:
    """Install packages into the virtual environment.

    Args:
        venv_dir: Path to the venv directory.
        packages: List of pip package names to install.
        progress_callback: Optional callback for progress updates (percent, message).

    Returns:
        Tuple of (success, message).
    """
    python_path = get_venv_python_path(venv_dir)
    env = _get_clean_env()
    kwargs = _get_subprocess_kwargs()

    cmd = [
        python_path,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--disable-pip-version-check",
        "--prefer-binary",
    ] + packages

    if progress_callback:
        progress_callback(20, f"Installing: {', '.join(packages)}...")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        **kwargs,
    )

    if result.returncode != 0:
        error_output = result.stderr or result.stdout or "Unknown error"
        # Truncate long error messages
        if len(error_output) > 1000:
            error_output = "..." + error_output[-1000:]
        return False, f"pip install failed:\n{error_output}"

    return True, "Packages installed successfully."


class DepsInstallWorker(QThread):
    """Worker thread for creating a venv and installing dependencies."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def run(self):
        """Execute venv creation and dependency installation."""
        try:
            venv_dir = get_venv_dir()

            # Step 1: Create venv if needed
            if not venv_exists():
                self.progress.emit(5, "Creating virtual environment...")
                try:
                    create_venv(venv_dir)
                except RuntimeError as e:
                    self.finished.emit(False, str(e))
                    return
            self.progress.emit(10, "Virtual environment ready.")

            # Step 2: Verify pip
            self.progress.emit(12, "Verifying pip...")
            python_path = get_venv_python_path(venv_dir)
            env = _get_clean_env()
            kwargs = _get_subprocess_kwargs()

            result = subprocess.run(
                [python_path, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                **kwargs,
            )
            if result.returncode != 0:
                self.finished.emit(
                    False,
                    "pip is not available in the virtual environment.\n"
                    "Please install dependencies manually:\n"
                    "pip install earthaccess geopandas shapely pandas",
                )
                return
            self.progress.emit(15, "pip is available.")

            # Step 3: Install missing packages
            missing = get_missing_packages()
            if not missing:
                self.finished.emit(True, "All dependencies are already installed.")
                return

            self.progress.emit(20, f"Installing: {', '.join(missing)}...")
            success, message = install_packages(
                venv_dir,
                missing,
                progress_callback=lambda p, m: self.progress.emit(
                    20 + int(p * 0.65), m
                ),
            )
            if not success:
                self.finished.emit(False, message)
                return
            self.progress.emit(85, "Packages installed.")

            # Step 4: Add venv to sys.path
            self.progress.emit(90, "Configuring package paths...")
            ensure_venv_packages_available()

            # Step 5: Verify imports
            self.progress.emit(95, "Verifying installations...")
            still_missing = get_missing_packages()
            if still_missing:
                self.finished.emit(
                    False,
                    f"The following packages could not be verified: "
                    f"{', '.join(still_missing)}.\n"
                    "You may need to restart QGIS for changes to take effect.",
                )
            else:
                self.progress.emit(100, "All dependencies installed!")
                self.finished.emit(True, "All dependencies installed successfully!")

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Installation timed out after 10 minutes.")
        except Exception as e:
            self.finished.emit(False, f"Unexpected error: {str(e)}")
