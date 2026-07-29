"""Evidence-refine timing report shape and retention."""

from __future__ import annotations

from api.analytics.homeworld_locator.evidence_refine_report import (
    EvidenceRefineCounts,
    EvidenceRefineInnerTimingMs,
    EvidenceRefineOuterTimingMs,
    build_evidence_refine_report,
    evidence_refine_report_to_wire,
    summarize_evidence_refine_reports,
)
from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    clear_evidence_refine_reports,
    recent_evidence_refine_reports,
    record_evidence_refine_report,
    reset_evidence_refine_report_history_for_tests,
)
from api.services.layout_prior_diagnostics_service import get_layout_prior_reports_wire


def setup_function() -> None:
    reset_evidence_refine_report_history_for_tests()
    clear_evidence_refine_reports()


def teardown_function() -> None:
    clear_evidence_refine_reports()
    reset_evidence_refine_report_history_for_tests()


def test_evidence_refine_report_wire_and_summary() -> None:
    report = build_evidence_refine_report(
        game_id=663307,
        turn=60,
        perspective=2,
        baseline_turn=1,
        timing_inner=EvidenceRefineInnerTimingMs(
            origin_distance_ms=80.0,
            single_starbase_ms=5.0,
            observation_upsert_ms=15.0,
            total_ms=100.0,
        ),
        timing_outer=EvidenceRefineOuterTimingMs(
            load_game_state_ms=0.5,
            load_prior_ms=1.0,
            refine_inner_ms=100.0,
            persist_ms=2.0,
            total_ms=103.5,
        ),
        counts=EvidenceRefineCounts(
            ship_count=200,
            candidate_count=400,
            prior_observation_count=1000,
            origin_distance_matches=12,
            new_observations_appended=3,
            single_starbase_promotions=0,
        ),
    )
    record_evidence_refine_report(report)
    wire = evidence_refine_report_to_wire(report)
    assert wire["timingInner"]["originDistanceMs"] == 80.0
    assert wire["timingInner"]["observationUpsertMs"] == 15.0
    assert wire["counts"]["candidateCount"] == 400
    assert wire["counts"]["priorObservationCount"] == 1000
    assert wire["counts"]["newObservationsAppended"] == 3

    payload = get_layout_prior_reports_wire(game_id=663307, perspective=2, turn=60)
    assert len(payload["evidenceRefineReports"]) == 1
    assert payload["evidenceRefineSummary"]["sumOriginDistanceMs"] == 80.0
    assert payload["evidenceRefineSummary"]["maxOuterTotalTurn"] == 60
    assert recent_evidence_refine_reports(game_id=1, perspective=2) == ()


def test_summarize_empty() -> None:
    summary = summarize_evidence_refine_reports(())
    assert summary["reportCount"] == 0
    assert summary["sumOuterTotalMs"] == 0.0
