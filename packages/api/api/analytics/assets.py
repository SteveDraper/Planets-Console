"""Resolve paths to fixed analytic asset directories under the repo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ANALYTICS_ASSETS_SEGMENT = Path("assets") / "analytics"


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the workspace root (directory containing ``assets/analytics``)."""
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / _ANALYTICS_ASSETS_SEGMENT).is_dir():
            return candidate
    raise FileNotFoundError(
        f"could not locate repo root from {__file__!r}: "
        f"no {_ANALYTICS_ASSETS_SEGMENT} directory found while walking parents"
    )


def analytics_assets_dir(analytic_name: str) -> Path:
    """Return ``{repo_root}/assets/analytics/{analytic_name}/``."""
    if not analytic_name:
        raise ValueError("analytic_name must be a non-empty string")
    return repo_root() / _ANALYTICS_ASSETS_SEGMENT / analytic_name
