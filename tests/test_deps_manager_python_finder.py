from pathlib import Path

import pytest

from nasa_opera import deps_manager


def test_find_python_executable_uses_macos_qgis_app_python(tmp_path, monkeypatch):
    """macOS QGIS may expose the app launcher as sys.executable."""
    contents_dir = tmp_path / "QGIS.app" / "Contents"
    qgis_launcher = contents_dir / "MacOS" / "QGIS"
    bundled_python = contents_dir / "MacOS" / "bin" / "python3"

    qgis_launcher.parent.mkdir(parents=True)
    qgis_launcher.touch()
    bundled_python.parent.mkdir(parents=True)
    bundled_python.touch()

    monkeypatch.setattr(deps_manager.sys, "executable", str(qgis_launcher))
    monkeypatch.setattr(deps_manager.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        deps_manager,
        "_python_candidate_matches_runtime",
        lambda path: Path(path) == bundled_python,
    )

    assert deps_manager._find_python_executable() == str(bundled_python)


def test_find_python_executable_raises_instead_of_returning_qgis_launcher(
    tmp_path, monkeypatch
):
    qgis_launcher = tmp_path / "QGIS.app" / "Contents" / "MacOS" / "QGIS"
    qgis_launcher.parent.mkdir(parents=True)
    qgis_launcher.touch()

    monkeypatch.setattr(deps_manager.sys, "executable", str(qgis_launcher))
    monkeypatch.setattr(deps_manager.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        deps_manager, "_python_candidate_matches_runtime", lambda _path: False
    )

    with pytest.raises(RuntimeError, match="Could not find a Python executable"):
        deps_manager._find_python_executable()
