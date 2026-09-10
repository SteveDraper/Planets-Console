"""Resolve bundled SPA and analytics asset roots inside a PyInstaller onedir."""

from __future__ import annotations

import os
import sys
from pathlib import Path

FRONTEND_DIST_ENV = "FRONTEND_DIST"
SPA_DIST_RELATIVE = Path("packages") / "frontend" / "dist"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory that contains bundled datas (``sys._MEIPASS`` when frozen)."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return _source_repo_root()


def _source_repo_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "assets" / "analytics").is_dir():
            return candidate
    raise FileNotFoundError(f"could not locate repo root from {__file__!r}: no assets/analytics")


def spa_dist_dir() -> Path:
    return resource_root() / SPA_DIST_RELATIVE


def apply_frontend_dist_env() -> Path:
    """Point ``FRONTEND_DIST`` at the bundled SPA. Do not use a CI-absolute freeze."""
    dist = spa_dist_dir()
    os.environ[FRONTEND_DIST_ENV] = str(dist)
    return dist
