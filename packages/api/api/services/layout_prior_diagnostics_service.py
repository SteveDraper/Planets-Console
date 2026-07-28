"""BFF-facing facade for homeworld layout-prior solver run reports (#274).

Keeps ``api.analytics.homeworld_locator`` report history behind the allowed
Core API service import surface (see ``.cursor/rules/bff.mdc``).
"""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.layout_prior_run_history import (
    clear_layout_prior_reports,
    recent_layout_prior_reports_wire,
    reset_layout_prior_report_history_for_tests,
)

__all__ = [
    "clear_layout_prior_reports",
    "get_layout_prior_reports_wire",
    "reset_layout_prior_report_history_for_tests",
]


def get_layout_prior_reports_wire(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> dict[str, Any]:
    """Return newest-first layout-prior reports for one shell context."""
    return {
        "shell": {
            "gameId": game_id,
            "perspective": perspective,
            "turn": turn,
        },
        "reports": recent_layout_prior_reports_wire(
            game_id=game_id,
            perspective=perspective,
            turn=turn,
        ),
    }
