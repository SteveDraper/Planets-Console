"""OS per-user console data directory for the packaged file backend and support logs.

Clone / ``run_dev`` / ``run_deploy`` keep repo ``.config.yaml`` and
``ApiConfig.storage_root`` ``./.data``. This helper is for **console package**
launch only: expand ``~`` / ``%LOCALAPPDATA%`` in process and never freeze a
CI-runner absolute path into YAML.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

# Folder name matches the installed product display name.
CONSOLE_PACKAGE_DISPLAY_NAME = "Planets Console"


class ConsoleDataDirectoryError(RuntimeError):
    """Console data directory could not be resolved for this OS."""


def console_data_directory() -> Path:
    """Return the OS per-user **console data directory** without creating it.

    macOS: ``~/Library/Application Support/Planets Console/``
    Windows: ``%LOCALAPPDATA%\\Planets Console\\``

    Packaged ``api.storage_root`` and support logs both point here. Independent
    of install location so **install-over** does not wipe games or account API
    keys. v1 **console package** is macOS and Windows only.
    """
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / CONSOLE_PACKAGE_DISPLAY_NAME
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise ConsoleDataDirectoryError(
                "LOCALAPPDATA is not set; cannot resolve the console data directory."
            )
        return Path(os.path.expandvars(local_app_data)) / CONSOLE_PACKAGE_DISPLAY_NAME
    raise ConsoleDataDirectoryError(
        f"Unsupported platform for the console data directory: {system!r}"
    )


def packaged_file_backend_override_specs() -> tuple[str, ...]:
    """``--config`` specs that point the file backend at the console data directory.

    The **process host** passes these into ``load_config`` with
    ``discover_default=False`` so packaged launch does not cwd-walk
    ``.config.yaml``.
    """
    return (
        "api.storage_backend=file",
        f"api.storage_root={console_data_directory()}",
    )
