"""Installed console package identity (display name, OS ids, version).

Keep these strings aligned with ADR 0029. Do not rename bundle id,
AppUserModelID, or Inno AppId after v1 ships.

Version comes from root ``pyproject.toml`` ``[project].version``. A frozen
process host reads the same value from a one-line sidecar the bundler ships.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

# Folder name and Dock / taskbar / About display name.
CONSOLE_PACKAGE_DISPLAY_NAME = "Planets Console"

# macOS Info.plist CFBundleIdentifier. Do not change after first ship.
CFBUNDLE_IDENTIFIER = "com.github.stevedraper.planets-console"

# Windows Application User Model ID. Do not change after first ship.
APP_USER_MODEL_ID = "SteveDraper.PlanetsConsole"

# Inno Setup AppId (per-user). Do not change after first ship.
INNO_APP_ID = "{933C1FA0-3D30-4611-AE34-2F7C14C5253B}"

# Dest name under the frozen resource root (``sys._MEIPASS``).
VERSION_SIDECAR_NAME = "console_package_version.txt"

_ROOT_PROJECT_NAME = "planets-console"


def version_from_pyproject(repo_root: Path) -> str:
    """Read ``[project].version`` from the workspace root pyproject.toml."""
    payload = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("root pyproject.toml is missing [project].version")
    return version


def write_version_sidecar(path: Path, version: str) -> None:
    """Write a one-line version file for the frozen process host."""
    if not version:
        raise ValueError("version sidecar cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{version}\n", encoding="utf-8")


def read_version_sidecar(path: Path) -> str:
    """Read a one-line version sidecar written by ``write_version_sidecar``."""
    if not path.is_file():
        raise FileNotFoundError(f"version sidecar is missing: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError(f"version sidecar is empty: {path}")
    return version


def console_package_version() -> str:
    """Return the console package version from pyproject, or the frozen sidecar."""
    frozen_root = _frozen_resource_root()
    if frozen_root is not None:
        return read_version_sidecar(frozen_root / VERSION_SIDECAR_NAME)
    return version_from_pyproject(_workspace_root())


def _frozen_resource_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    return Path(meipass)


def _workspace_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        if payload.get("project", {}).get("name") == _ROOT_PROJECT_NAME:
            return candidate
    raise FileNotFoundError(
        f"could not locate workspace root pyproject.toml ({_ROOT_PROJECT_NAME}) from {__file__!r}"
    )
