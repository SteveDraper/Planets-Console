"""Shared table-stream errors."""

from __future__ import annotations

from api.errors import PlanetsConsoleError


class TableStreamScopeAlreadyActive(PlanetsConsoleError):
    """Another NDJSON table stream already owns this turn scope."""
