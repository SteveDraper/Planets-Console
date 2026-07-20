"""Unit tests for OS machine id reader branches."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from api.credentials.machine_id import (
    MachineIdError,
    _read_linux_machine_id,
    _read_macos_platform_uuid,
    _read_windows_machine_guid,
    read_os_machine_id,
)


def test_read_os_machine_id_dispatches_darwin():
    with (
        patch("api.credentials.machine_id.platform.system", return_value="Darwin"),
        patch(
            "api.credentials.machine_id._read_macos_platform_uuid",
            return_value="MAC-UUID",
        ) as mock_mac,
    ):
        assert read_os_machine_id() == "MAC-UUID"
        mock_mac.assert_called_once()


def test_read_os_machine_id_dispatches_windows():
    with (
        patch("api.credentials.machine_id.platform.system", return_value="Windows"),
        patch(
            "api.credentials.machine_id._read_windows_machine_guid",
            return_value="WIN-GUID",
        ) as mock_win,
    ):
        assert read_os_machine_id() == "WIN-GUID"
        mock_win.assert_called_once()


def test_read_os_machine_id_dispatches_linux():
    with (
        patch("api.credentials.machine_id.platform.system", return_value="Linux"),
        patch(
            "api.credentials.machine_id._read_linux_machine_id",
            return_value="linux-id",
        ) as mock_linux,
    ):
        assert read_os_machine_id() == "linux-id"
        mock_linux.assert_called_once()


def test_read_os_machine_id_unsupported():
    with patch("api.credentials.machine_id.platform.system", return_value="FreeBSD"):
        with pytest.raises(MachineIdError, match="Unsupported"):
            read_os_machine_id()


def test_macos_parses_ioreg():
    sample = '  "IOPlatformUUID" = "ABCD-1234"\n'
    with patch(
        "api.credentials.machine_id.subprocess.check_output",
        return_value=sample,
    ):
        assert _read_macos_platform_uuid() == "ABCD-1234"


def test_macos_missing_uuid():
    with patch(
        "api.credentials.machine_id.subprocess.check_output",
        return_value="no uuid here",
    ):
        with pytest.raises(MachineIdError, match="IOPlatformUUID"):
            _read_macos_platform_uuid()


def test_linux_reads_machine_id():
    with patch("api.credentials.machine_id.Path.read_text", return_value="abc123\n"):
        assert _read_linux_machine_id() == "abc123"


def test_linux_missing_file():
    with patch(
        "api.credentials.machine_id.Path.read_text",
        side_effect=OSError("missing"),
    ):
        with pytest.raises(MachineIdError, match="machine-id"):
            _read_linux_machine_id()


def test_windows_reads_registry():
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.OpenKey.return_value.__exit__.return_value = None
    mock_winreg.QueryValueEx.return_value = ("GUID-VALUE", 1)
    with (
        patch("api.credentials.machine_id.sys.platform", "win32"),
        patch.dict("sys.modules", {"winreg": mock_winreg}),
    ):
        assert _read_windows_machine_guid() == "GUID-VALUE"


def test_windows_rejects_non_win32():
    with patch("api.credentials.machine_id.sys.platform", "darwin"):
        with pytest.raises(MachineIdError, match="non-Windows"):
            _read_windows_machine_guid()
