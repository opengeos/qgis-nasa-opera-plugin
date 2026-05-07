import os

from nasa_opera.utils.earthdata_credentials import (
    configure_earthdata_netrc_env,
    earthdata_netrc_paths,
    save_earthdata_credentials,
)


def test_windows_netrc_paths_prefer_underscore_name(tmp_path):
    assert earthdata_netrc_paths(home=tmp_path, platform="win32") == [
        tmp_path / "_netrc",
        tmp_path / ".netrc",
    ]


def test_configure_netrc_env_uses_existing_windows_dot_netrc(tmp_path, monkeypatch):
    dot_netrc = tmp_path / ".netrc"
    dot_netrc.write_text(
        "machine urs.earthdata.nasa.gov login user password pass\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("NETRC", raising=False)

    selected = configure_earthdata_netrc_env(home=tmp_path, platform="win32")

    assert selected == dot_netrc
    assert os.environ["NETRC"] == str(dot_netrc)


def test_save_earthdata_credentials_writes_windows_default_netrc(tmp_path, monkeypatch):
    monkeypatch.delenv("NETRC", raising=False)

    selected = save_earthdata_credentials(
        "new-user", "new-pass", home=tmp_path, platform="win32"
    )

    assert selected == tmp_path / "_netrc"
    assert os.environ["NETRC"] == str(selected)
    assert selected.read_text(encoding="utf-8") == (
        "machine urs.earthdata.nasa.gov\n" "  login new-user\n" "  password new-pass\n"
    )


def test_save_earthdata_credentials_replaces_existing_entry(tmp_path, monkeypatch):
    netrc_path = tmp_path / ".netrc"
    netrc_path.write_text(
        "machine example.com\n"
        "  login other\n"
        "  password secret\n"
        "machine urs.earthdata.nasa.gov\n"
        "  login old-user\n"
        "  password old-pass\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("NETRC", raising=False)

    save_earthdata_credentials("new-user", "new-pass", home=tmp_path, platform="linux")

    assert netrc_path.read_text(encoding="utf-8") == (
        "machine example.com\n"
        "  login other\n"
        "  password secret\n"
        "\n"
        "machine urs.earthdata.nasa.gov\n"
        "  login new-user\n"
        "  password new-pass\n"
    )
