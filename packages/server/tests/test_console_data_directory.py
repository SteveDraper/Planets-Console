"""OS console data directory helper for packaged launches."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from api.config import ApiConfig
from server.config import load_config, load_packaged_config
from server.console_data_directory import (
    CONSOLE_PACKAGE_DISPLAY_NAME,
    ConsoleDataDirectoryError,
    console_data_directory,
    packaged_file_backend_override_specs,
)


def test_macos_console_data_directory_expands_home():
    home = Path("/tmp/packaged-home")
    with (
        patch("server.console_data_directory.platform.system", return_value="Darwin"),
        patch("server.console_data_directory.Path.home", return_value=home),
    ):
        assert console_data_directory() == (
            home / "Library" / "Application Support" / CONSOLE_PACKAGE_DISPLAY_NAME
        )


def test_windows_console_data_directory_expands_localappdata(monkeypatch):
    local = r"C:\Users\tester\AppData\Local"
    monkeypatch.setenv("LOCALAPPDATA", local)
    with patch("server.console_data_directory.platform.system", return_value="Windows"):
        assert console_data_directory() == Path(local) / CONSOLE_PACKAGE_DISPLAY_NAME


def test_windows_console_data_directory_requires_localappdata(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with patch("server.console_data_directory.platform.system", return_value="Windows"):
        with pytest.raises(ConsoleDataDirectoryError, match="LOCALAPPDATA"):
            console_data_directory()


def test_unsupported_platform_raises():
    with patch("server.console_data_directory.platform.system", return_value="Linux"):
        with pytest.raises(ConsoleDataDirectoryError, match="Unsupported"):
            console_data_directory()


def test_macos_console_data_directory_is_not_applications_install():
    home = Path("/Users/tester")
    with (
        patch("server.console_data_directory.platform.system", return_value="Darwin"),
        patch("server.console_data_directory.Path.home", return_value=home),
    ):
        data_dir = console_data_directory()
    assert data_dir == home / "Library" / "Application Support" / CONSOLE_PACKAGE_DISPLAY_NAME
    assert data_dir != Path("/Applications") / f"{CONSOLE_PACKAGE_DISPLAY_NAME}.app"
    assert "/Applications/" not in data_dir.as_posix()


def test_windows_console_data_directory_is_not_per_user_programs_install(monkeypatch):
    local = r"C:\Users\tester\AppData\Local"
    monkeypatch.setenv("LOCALAPPDATA", local)
    monkeypatch.setattr(
        sys,
        "executable",
        rf"{local}\Programs\{CONSOLE_PACKAGE_DISPLAY_NAME}\{CONSOLE_PACKAGE_DISPLAY_NAME}.exe",
    )
    with patch("server.console_data_directory.platform.system", return_value="Windows"):
        data_dir = console_data_directory()
    install_dir = Path(local) / "Programs" / CONSOLE_PACKAGE_DISPLAY_NAME
    assert data_dir == Path(local) / CONSOLE_PACKAGE_DISPLAY_NAME
    assert data_dir != install_dir
    assert data_dir != Path(sys.executable).parent


def test_console_data_directory_ignores_cwd_config_and_dot_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".config.yaml").write_text("api:\n  storage_root: ./.data\n", encoding="utf-8")
    (tmp_path / ".data").mkdir()
    home = tmp_path / "home"
    with (
        patch("server.console_data_directory.platform.system", return_value="Darwin"),
        patch("server.console_data_directory.Path.home", return_value=home),
    ):
        result = console_data_directory()
    assert result == home / "Library" / "Application Support" / CONSOLE_PACKAGE_DISPLAY_NAME
    assert result != Path("./.data")
    assert not result.exists()


def test_packaged_override_specs_set_file_backend_storage_root():
    data_dir = Path("/tmp/packaged-home/Library/Application Support/Planets Console")
    with patch(
        "server.console_data_directory.console_data_directory",
        return_value=data_dir,
    ):
        specs = packaged_file_backend_override_specs()
    assert specs == (
        "api.storage_backend=file",
        f"api.storage_root={data_dir}",
    )


def test_load_packaged_config_ignores_cwd_config_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".config.yaml").write_text(
        "api:\n  storage_backend: file\n  storage_root: ./.data\n  include_dummy_data: true\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "Library" / "Application Support" / "Planets Console"
    with patch(
        "server.console_data_directory.console_data_directory",
        return_value=data_dir,
    ):
        root = load_packaged_config()
    assert root.api.storage_backend == "file"
    assert root.api.storage_root == str(data_dir)
    assert root.api.include_dummy_data is False
    assert ApiConfig().storage_root == "./.data"


def test_load_packaged_config_extra_overrides_apply_after_packaged_specs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".config.yaml").write_text(
        "api:\n  include_dummy_data: true\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "Library" / "Application Support" / "Planets Console"
    with patch(
        "server.console_data_directory.console_data_directory",
        return_value=data_dir,
    ):
        root = load_packaged_config(override_specs=["server.port=9000"])
    assert root.api.storage_backend == "file"
    assert root.api.storage_root == str(data_dir)
    assert root.api.include_dummy_data is False
    assert root.server.port == 9000


def test_load_config_still_discovers_cwd_yaml_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".config.yaml").write_text(
        "server: {}\napi:\n  storage_backend: file\n  storage_root: ./.data\nbff: {}\n",
        encoding="utf-8",
    )
    root = load_config()
    assert root.api.storage_backend == "file"
    assert root.api.storage_root == "./.data"
