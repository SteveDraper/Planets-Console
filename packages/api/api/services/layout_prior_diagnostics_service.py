"""BFF-facing facade for homeworld locator diagnostics (#274).

Layout-prior solver reports plus evidence-refine / baseline timing breakdowns.
"""

from __future__ import annotations

from typing import Any

from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    clear_baseline_reports,
    clear_ensure_failure_reports,
    clear_evidence_refine_reports,
    evidence_refine_summary_wire,
    recent_baseline_reports_wire,
    recent_ensure_failure_reports_wire,
    recent_evidence_refine_reports_wire,
    reset_evidence_refine_report_history_for_tests,
)
from api.analytics.homeworld_locator.layout_prior_run_history import (
    clear_layout_prior_reports,
    recent_layout_prior_reports_wire,
    reset_layout_prior_report_history_for_tests,
)

__all__ = [
    "clear_homeworld_diagnostics_for_tests",
    "get_layout_prior_reports_wire",
    "reset_layout_prior_report_history_for_tests",
]


def clear_homeworld_diagnostics_for_tests() -> None:
    clear_layout_prior_reports()
    clear_evidence_refine_reports()
    clear_baseline_reports()
    clear_ensure_failure_reports()
    reset_layout_prior_report_history_for_tests()
    reset_evidence_refine_report_history_for_tests()


def get_layout_prior_reports_wire(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> dict[str, Any]:
    """Return homeworld diagnostics for one shell context.

    ``reports`` remains layout-prior solver runs for the shell turn.
    Evidence-refine reports are filtered by game + perspective (all turns in
    the unwind) so a late-shell load can attribute DAG cost.
    """
    refine_reports = recent_evidence_refine_reports_wire(
        game_id=game_id,
        perspective=perspective,
    )
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
        "evidenceRefineReports": refine_reports,
        "evidenceRefineSummary": evidence_refine_summary_wire(
            game_id=game_id,
            perspective=perspective,
        ),
        "baselineReports": recent_baseline_reports_wire(
            game_id=game_id,
            perspective=perspective,
        ),
        "ensureFailures": recent_ensure_failure_reports_wire(
            game_id=game_id,
            perspective=perspective,
        ),
    }
