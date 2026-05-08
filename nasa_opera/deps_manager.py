"""
Dependency Manager for NASA OPERA Plugin.

Manages a virtual environment for plugin dependencies
to avoid polluting the QGIS built-in Python environment.

The venv is created at ~/.qgis_nasa_opera/venv_pyX.Y and its
site-packages directory is added to sys.path at runtime.

All ``subprocess`` calls in this module use list-form argv built from
internal constants (the resolved Python interpreter, the resolved ``uv``
binary, fixed flags) and never accept user-supplied input or run with
``shell=True``. The ``# nosec`` annotations on the import and call sites
document this explicitly for the plugins.qgis.org Bandit scan.
"""

import importlib
import os
import platform
import shutil
import subprocess  # nosec B404
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QThread, pyqtSignal

REQUIRED_PACKAGES = [
    ("earthaccess", "earthaccess"),
    ("geopandas", "geopandas"),
    ("shapely", "shapely"),
    ("pandas", "pandas"),
]

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".qgis_nasa_opera")
PYTHON_VERSION = f"py{sys.version_info.major}.{sys.version_info.minor}"
INSTALL_TIMEOUT_SECONDS = 1800


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

    On Windows, suppresses the console window that would otherwise pop up
    for each subprocess invocation.

    Returns:
        Dict of kwargs to pass to subprocess.run().
    """
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _is_python_executable_name(path: str) -> bool:
    """Return True when a path name looks like a Python interpreter."""
    name = os.path.basename(path).lower()
    return name in ("python", "python3", "python.exe", "python3.exe") or (
        name.startswith("python") and name.endswith(".exe")
    )


def _is_macos_qgis_app_bundle_python(path: str) -> bool:
    """Return True for Python binaries inside a QGIS macOS .app bundle."""
    if not (platform.system() == "Darwin" or sys.platform == "darwin"):
        return False
    parts = os.path.abspath(path).split(os.sep)
    for idx, part in enumerate(parts):
        lower = part.lower()
        if not (lower.startswith("qgis") and lower.endswith(".app")):
            continue
        return idx + 1 < len(parts) and parts[idx + 1] == "Contents"
    return False


def _python_candidate_matches_runtime(path: str) -> bool:
    """Return True when a candidate is executable and matches QGIS Python."""
    if not path or not os.path.isfile(path) or not _is_python_executable_name(path):
        return False

    if _is_macos_qgis_app_bundle_python(path):
        return False

    try:
        result = subprocess.run(  # nosec B603
            [
                path,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=_get_clean_env(),
            **_get_subprocess_kwargs(),
        )
    except Exception:
        return False

    runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return result.returncode == 0 and result.stdout.strip() == runtime_version


def _candidate_python_paths() -> List[str]:
    """Return possible Python interpreter paths for QGIS-bundled Python."""
    candidates = []
    exe_dir = os.path.dirname(sys.executable)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"

    for attr in ("_base_executable", "executable"):
        value = getattr(sys, attr, None)
        if value:
            candidates.append(value)

    for attr in ("_base_prefix", "base_prefix", "prefix", "exec_prefix"):
        prefix = getattr(sys, attr, None)
        if not prefix:
            continue
        candidates.extend(
            [
                os.path.join(prefix, "python.exe"),
                os.path.join(prefix, "bin", "python3"),
                os.path.join(prefix, "bin", "python"),
                os.path.join(prefix, "Versions", py_ver, "bin", "python3"),
                os.path.join(prefix, "Versions", "Current", "bin", "python3"),
            ]
        )

    candidates.extend(
        [
            os.path.join(exe_dir, "python.exe"),
            os.path.join(exe_dir, "python3.exe"),
            os.path.join(exe_dir, "python3"),
            os.path.join(exe_dir, "python"),
        ]
    )

    # QGIS Windows layout:
    #   .../QGIS 3.x/bin/qgis-bin.exe
    #   .../QGIS 3.x/apps/Python312/python.exe
    apps_dir = os.path.join(os.path.dirname(exe_dir), "apps")
    if os.path.isdir(apps_dir):
        for entry in sorted(os.listdir(apps_dir), reverse=True):
            if entry.lower().startswith("python"):
                candidates.append(os.path.join(apps_dir, entry, "python.exe"))

    # QGIS macOS app layout. Depending on package/version, the launcher may be
    # Contents/MacOS/QGIS while Python lives under MacOS/bin or Frameworks.
    current = exe_dir
    for _ in range(5):
        if os.path.basename(current) == "Contents":
            contents_dir = current
            candidates.extend(
                [
                    os.path.join(contents_dir, "MacOS", "bin", "python3"),
                    os.path.join(contents_dir, "MacOS", "bin", "python"),
                    os.path.join(
                        contents_dir,
                        "Frameworks",
                        "Python.framework",
                        "Versions",
                        py_ver,
                        "bin",
                        "python3",
                    ),
                    os.path.join(
                        contents_dir,
                        "Frameworks",
                        "Python.framework",
                        "Versions",
                        "Current",
                        "bin",
                        "python3",
                    ),
                    os.path.join(contents_dir, "Resources", "python", "bin", "python3"),
                ]
            )
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    for name in ("python3", "python"):
        which_python = shutil.which(name)
        if which_python:
            candidates.append(which_python)

    # Preserve order while removing duplicates.
    unique = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _find_python_executable() -> str:
    """Find a real Python executable for subprocess calls.

    QGIS can expose the application launcher as ``sys.executable`` on Windows
    and macOS. Passing that launcher to uv or venv causes QGIS to receive
    Python flags such as ``-I`` and ``-c`` as layer/data-source arguments, so
    this function verifies candidates before returning them.

    Returns:
        Path to a Python executable matching the current QGIS Python version.

    Raises:
        RuntimeError: If no suitable Python executable can be found.
    """
    for candidate in _candidate_python_paths():
        if _python_candidate_matches_runtime(candidate):
            return candidate

    candidates = "\n".join(f"  - {path}" for path in _candidate_python_paths())
    raise RuntimeError(
        "Could not find a Python executable matching the QGIS Python runtime.\n"
        f"QGIS sys.executable: {sys.executable}\n"
        f"Python version: {sys.version_info.major}.{sys.version_info.minor}\n"
        "Checked candidates:\n"
        f"{candidates or '  - none'}"
    )


def _create_venv_with_env_builder(venv_dir: str) -> bool:
    """Attempt to create a virtual environment using venv.EnvBuilder (in-process).

    .. warning::
        ``EnvBuilder`` internally uses ``sys.executable`` to copy the Python
        binary into the venv.  On QGIS Windows ``sys.executable`` is
        ``qgis-bin.exe``, so this would copy QGIS itself and later subprocess
        calls would launch a new QGIS instance.  Therefore this function is
        **skipped** when ``sys.executable`` does not look like a Python
        interpreter.

    Args:
        venv_dir: Path where the venv should be created.

    Returns:
        True if the venv was created and the Python executable exists.
    """
    # Guard: only safe when sys.executable is actually Python.
    exe_name = os.path.basename(sys.executable).lower()
    if exe_name not in ("python.exe", "python3.exe", "python", "python3"):
        return False

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
        shutil.copy2(_find_python_executable(), python_path)
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
    subprocess.run(  # nosec B603
        [python_path, "-m", "ensurepip", "--upgrade"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        **kwargs,
    )

    # Verify pip works
    result = subprocess.run(  # nosec B603
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

    When uv is available, uses ``uv venv`` which is faster and does not
    require pip to be bootstrapped inside the venv.

    Otherwise uses a multi-strategy approach to handle embedded Python
    environments (e.g. QGIS on Windows) where ``sys.executable`` may point
    to ``qgis-bin.exe`` rather than ``python.exe``.

    Pip fallback strategy order:
        1. Subprocess using the real Python executable found by
           ``_find_python_executable()`` (primary, works on Windows QGIS).
        2. In-process ``venv.EnvBuilder`` (fallback, only when
           ``sys.executable`` is already a Python interpreter).
        3. Recovery: copy the real Python executable into the venv when the
           directory was created but the executable is missing.

    Args:
        venv_dir: Path where the venv should be created.

    Returns:
        Path to the Python executable inside the newly created venv.

    Raises:
        RuntimeError: If venv creation fails after all strategies.
    """
    from .uv_manager import get_uv_path, uv_exists

    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)

    python_path = get_venv_python_path(venv_dir)
    env = _get_clean_env()
    kwargs = _get_subprocess_kwargs()

    python_exe = None
    python_lookup_error = ""
    try:
        python_exe = _find_python_executable()
    except RuntimeError as exc:
        python_lookup_error = str(exc)

    # Strategy 0: Use uv venv when available (fastest, no pip needed). On
    # official macOS QGIS app bundles, require uv-managed Python instead of
    # reusing QGIS's app-bundle Python wrapper for venv creation.
    if uv_exists():
        uv_path = get_uv_path()
        uv_python = python_exe or f"{sys.version_info.major}.{sys.version_info.minor}"
        cmd = [uv_path, "venv"]
        if python_exe is None:
            cmd.append("--managed-python")
        cmd += ["--python", uv_python, venv_dir]
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **kwargs,
        )
        if result.returncode == 0 and os.path.isfile(python_path):
            return python_path
        # uv venv failed — clean up and fall through to pip strategies
        _cleanup_partial_venv(venv_dir)

    # Strategy 1: Subprocess with the real Python executable
    subprocess_error = ""
    if python_exe is None:
        raise RuntimeError(python_lookup_error)

    cmd = [python_exe, "-m", "venv", venv_dir]
    result = subprocess.run(  # nosec B603
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

    # Clean up partial venv before retrying
    _cleanup_partial_venv(venv_dir)

    # Strategy 2: In-process EnvBuilder (skipped when sys.executable is not Python)
    if _create_venv_with_env_builder(venv_dir):
        return _verify_pip_and_return(python_path)

    _cleanup_partial_venv(venv_dir)

    # Strategy 3: Create venv without pip, then copy Python executable if needed
    strategy3_error = ""
    try:
        result2 = subprocess.run(  # nosec B603
            [python_exe, "-m", "venv", "--without-pip", venv_dir],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            **kwargs,
        )
        if result2.returncode == 0:
            if not os.path.isfile(python_path):
                _try_copy_python_executable(venv_dir)
            if os.path.isfile(python_path):
                return _verify_pip_and_return(python_path)
        else:
            strategy3_error = result2.stderr or result2.stdout or ""
    except Exception as exc:
        strategy3_error = f"{type(exc).__name__}: {exc}"

    # All strategies failed
    details = [
        f"sys.executable: {sys.executable}",
        f"Python found: {python_exe}",
        f"Target venv: {venv_dir}",
        f"Expected python: {python_path}",
        f"Platform: {sys.platform}",
    ]
    if subprocess_error:
        details.append(f"Subprocess error: {subprocess_error}")
    if strategy3_error:
        details.append(f"Strategy 3 error: {strategy3_error}")

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

    Uses uv when available for significantly faster installation,
    falling back to pip otherwise.

    Args:
        venv_dir: Path to the venv directory.
        packages: List of pip package names to install.
        progress_callback: Optional callback for progress updates (percent, message).

    Returns:
        Tuple of (success, message).
    """
    from .uv_manager import get_uv_path, uv_exists

    python_path = get_venv_python_path(venv_dir)
    env = _get_clean_env()
    kwargs = _get_subprocess_kwargs()

    use_uv = uv_exists()
    if use_uv:
        uv_path = get_uv_path()
        cmd = [
            uv_path,
            "pip",
            "install",
            "--python",
            python_path,
            "--upgrade",
        ] + packages
    else:
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
        installer = "uv" if use_uv else "pip"
        progress_callback(20, f"Installing ({installer}): {', '.join(packages)}...")

    result = subprocess.run(  # nosec B603
        cmd,
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
        env=env,
        **kwargs,
    )

    if result.returncode != 0:
        error_output = result.stderr or result.stdout or "Unknown error"
        # Truncate long error messages
        if len(error_output) > 1000:
            error_output = "..." + error_output[-1000:]
        installer = "uv pip" if use_uv else "pip"
        return False, f"{installer} install failed:\n{error_output}"

    return True, "Packages installed successfully."


class DepsInstallWorker(QThread):
    """Worker thread for creating a venv and installing dependencies."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def run(self):
        """Execute uv download, venv creation, and dependency installation."""
        try:
            from .uv_manager import download_uv, uv_exists

            start_time = time.time()
            venv_dir = get_venv_dir()

            # Step 0: Download uv if needed (fast package installer)
            if not uv_exists():
                self.progress.emit(2, "Downloading uv package installer...")
                success, msg = download_uv(
                    progress_callback=lambda p, m: self.progress.emit(
                        2 + int(p * 0.03), m
                    ),
                )
                if not success:
                    # Non-fatal: fall back to pip
                    self.progress.emit(5, "uv unavailable, using pip instead.")
                else:
                    self.progress.emit(5, "uv ready.")

            # Step 1: Create venv if needed
            if venv_exists() and not _python_candidate_matches_runtime(
                get_venv_python_path(venv_dir)
            ):
                self.progress.emit(
                    5, "Existing virtual environment is invalid, recreating..."
                )
                _cleanup_partial_venv(venv_dir)

            if not venv_exists():
                self.progress.emit(5, "Creating virtual environment...")
                try:
                    create_venv(venv_dir)
                except RuntimeError as e:
                    self.finished.emit(False, str(e))
                    return
            self.progress.emit(10, "Virtual environment ready.")

            # Step 2: Verify pip (only needed when not using uv)
            use_uv = uv_exists()
            if not use_uv:
                self.progress.emit(12, "Verifying pip...")
                python_path = get_venv_python_path(venv_dir)
                env = _get_clean_env()
                kwargs = _get_subprocess_kwargs()

                result = subprocess.run(  # nosec B603
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
            self.progress.emit(15, "Package installer ready.")

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

            elapsed = time.time() - start_time
            if elapsed >= 60:
                minutes, seconds = divmod(int(round(elapsed)), 60)
                elapsed_str = f"{minutes}:{seconds:02d}"
            else:
                elapsed_str = f"{elapsed:.1f}s"

            if still_missing:
                self.finished.emit(
                    False,
                    f"The following packages could not be verified: "
                    f"{', '.join(still_missing)}.\n"
                    "You may need to restart QGIS for changes to take effect.",
                )
            else:
                self.progress.emit(100, f"All dependencies installed in {elapsed_str}!")
                self.finished.emit(
                    True,
                    f"All dependencies installed successfully in {elapsed_str}!",
                )

        except subprocess.TimeoutExpired:
            minutes = INSTALL_TIMEOUT_SECONDS // 60
            self.finished.emit(
                False, f"Installation timed out after {minutes} minutes."
            )
        except Exception as e:
            self.finished.emit(False, f"Unexpected error: {str(e)}")
