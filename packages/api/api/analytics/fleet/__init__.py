"""Core Fleet turn analytic."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID

_LAZY_EXPORTS = frozenset(
    {
        "REGISTRATION",
        "compute_fleet",
        "get_fleet",
        "iter_fleet_table_stream",
    }
)


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        from api.analytics.fleet import registration as registration_module

        return getattr(registration_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ANALYTIC_ID", *_LAZY_EXPORTS]
