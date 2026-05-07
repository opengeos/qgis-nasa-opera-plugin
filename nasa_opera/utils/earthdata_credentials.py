"""Helpers for Earthdata credential storage."""

import os
import sys
from pathlib import Path

EARTHDATA_MACHINE = "urs.earthdata.nasa.gov"


def _is_windows(platform=None):
    """Return True when paths should follow Windows netrc conventions."""
    return (platform or sys.platform).startswith("win")


def earthdata_netrc_paths(home=None, platform=None):
    """Return netrc paths in the order earthaccess should try them."""
    home_path = Path(home) if home is not None else Path.home()
    if _is_windows(platform):
        return [home_path / "_netrc", home_path / ".netrc"]
    return [home_path / ".netrc"]


def default_earthdata_netrc_path(home=None, platform=None):
    """Return the platform-default netrc path for writing credentials."""
    return earthdata_netrc_paths(home=home, platform=platform)[0]


def configure_earthdata_netrc_env(home=None, platform=None):
    """Point earthaccess at the configured netrc file when one exists.

    Earthaccess defaults to ``~/_netrc`` on Windows, while older versions of
    this plugin saved ``~/.netrc`` on every platform. Setting ``NETRC`` lets
    existing Windows installs keep working without asking for the password
    again.
    """
    configured_path = os.environ.get("NETRC")
    if configured_path:
        return Path(configured_path).expanduser()

    for netrc_path in earthdata_netrc_paths(home=home, platform=platform):
        if netrc_path.exists():
            os.environ["NETRC"] = str(netrc_path)
            return netrc_path

    return None


def save_earthdata_credentials(username, password, home=None, platform=None):
    """Save Earthdata credentials and return the path used."""
    netrc_path = default_earthdata_netrc_path(home=home, platform=platform)
    existing_lines = []
    if netrc_path.exists():
        with open(netrc_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    new_lines = []
    skip_machine = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith(f"machine {EARTHDATA_MACHINE}"):
            skip_machine = True
            continue
        if skip_machine and stripped and not stripped.startswith("machine"):
            continue
        skip_machine = False
        new_lines.append(line)

    if new_lines and new_lines[-1].strip():
        new_lines.append("\n")
    new_lines.extend(
        [
            f"machine {EARTHDATA_MACHINE}\n",
            f"  login {username}\n",
            f"  password {password}\n",
        ]
    )

    with open(netrc_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    if not _is_windows(platform):
        os.chmod(netrc_path, 0o600)

    os.environ["NETRC"] = str(netrc_path)
    return netrc_path
