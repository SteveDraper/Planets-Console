"""First-party OS native machine id reader for account API key HKDF.

Primary platforms: macOS and Windows 10+. Linux reads ``/etc/machine-id``
best-effort and fails closed when unreadable.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path


class MachineIdError(RuntimeError):
    """OS machine id could not be read (fail closed for obfuscation)."""


_IOPlatform_UUID_RE = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')


def read_os_machine_id() -> str:
    """Return the native machine id string for this host.

    Raises:
        MachineIdError: when the platform id cannot be obtained.
    """
    system = platform.system()
    if system == "Darwin":
        return _read_macos_platform_uuid()
    if system == "Windows":
        return _read_windows_machine_guid()
    if system == "Linux":
        return _read_linux_machine_id()
    raise MachineIdError(f"Unsupported platform for machine id: {system!r}")


def _read_macos_platform_uuid() -> str:
    try:
        raw = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MachineIdError("Failed to read macOS IOPlatformUUID.") from exc
    match = _IOPlatform_UUID_RE.search(raw)
    if match is None:
        raise MachineIdError("macOS IOPlatformUUID not found in ioreg output.")
    value = match.group(1).strip()
    if not value:
        raise MachineIdError("macOS IOPlatformUUID was empty.")
    return value


def _read_windows_machine_guid() -> str:
    if sys.platform != "win32":
        raise MachineIdError("Windows MachineGuid requested on a non-Windows host.")
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MachineIdError("winreg is unavailable.") from exc
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError as exc:
        raise MachineIdError("Failed to read Windows MachineGuid.") from exc
    if not isinstance(value, str) or not value.strip():
        raise MachineIdError("Windows MachineGuid was missing or empty.")
    return value.strip()


def _read_linux_machine_id() -> str:
    path = Path("/etc/machine-id")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MachineIdError("Failed to read /etc/machine-id.") from exc
    if not value:
        raise MachineIdError("/etc/machine-id was empty.")
    return value
