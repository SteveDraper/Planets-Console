"""Installed console package identity (display name, OS ids, version).

Keep these strings aligned with ADR 0029. Do not rename bundle id or
AppUserModelID after v1 ships.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Folder name and Dock / taskbar / About display name.
CONSOLE_PACKAGE_DISPLAY_NAME = "Planets Console"

# macOS Info.plist CFBundleIdentifier. Do not change after first ship.
CFBUNDLE_IDENTIFIER = "com.github.stevedraper.planets-console"

# Windows Application User Model ID. Do not change after first ship.
APP_USER_MODEL_ID = "SteveDraper.PlanetsConsole"

_VERSION_DISTRIBUTIONS = ("planets-console", "server")


def console_package_version() -> str:
    """Return the console package version from installed metadata (root pyproject)."""
    for dist_name in _VERSION_DISTRIBUTIONS:
        try:
            return version(dist_name)
        except PackageNotFoundError:
            continue
    return "0.1.0"
