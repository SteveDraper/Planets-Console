"""BFF inference cell displayStatus mapping for skip, residual, and failure."""

from bff.analytics.scores import inference_from_core


def _core_row(
    *,
    status: str,
    summary: str = "row",
    solution_count: int = 0,
    is_complete: bool = True,
    solutions: list | None = None,
    unexplained_military_delta_2x: int | None = None,
    placeholders: list | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "summary": summary,
        "solutionCount": solution_count,
        "isComplete": is_complete,
        "solutions": solutions if solutions is not None else [],
        "diagnostics": {},
    }
    if unexplained_military_delta_2x is not None:
        payload["unexplainedMilitaryDelta2x"] = unexplained_military_delta_2x
    if placeholders is not None:
        payload["placeholders"] = placeholders
    return payload


def test_skip_statuses_map_to_skipped_display_status() -> None:
    for status in (
        "viewpoint_owner",
        "dead",
        "full_alliance",
        "horwasp",
        "no_prior_turn",
        "player_not_found",
    ):
        shaped = inference_from_core(_core_row(status=status, summary="skipped row"), player_id=2)
        assert shaped["displayStatus"] == "skipped"
        assert shaped["status"] == status
        assert shaped["solutionCount"] == 0


def test_residual_statuses_map_to_matching_display_status() -> None:
    moderate = inference_from_core(
        _core_row(
            status="moderate_residual",
            unexplained_military_delta_2x=22,
            placeholders=[],
        ),
        player_id=3,
    )
    mine = inference_from_core(
        _core_row(
            status="mine_score_residual",
            unexplained_military_delta_2x=54,
            placeholders=[],
        ),
        player_id=4,
    )
    assert moderate["displayStatus"] == "moderate_residual"
    assert moderate["unexplainedMilitaryDelta2x"] == 22
    assert moderate["placeholders"] == []
    assert mine["displayStatus"] == "mine_score_residual"
    assert mine["unexplainedMilitaryDelta2x"] == 54


def test_failure_statuses_stay_failure() -> None:
    for status in ("no_exact_solution", "invalid_problem", "solver_error", "fetch_error"):
        shaped = inference_from_core(_core_row(status=status), player_id=5)
        assert shaped["displayStatus"] == "failure"
        assert shaped["status"] == status


def test_unavailable_build_inference_ignores_include_flag() -> None:
    from bff.analytics.scores import table_from_core

    payload = table_from_core(
        {"rows": [], "buildInferenceAvailable": False},
        include_build_inference=True,
    )
    assert payload["buildInferenceAvailable"] is False
    assert "includeBuildInference" not in payload
    assert "inferenceByRow" not in payload
    assert "Build inference" not in payload["columns"]


def test_exact_and_in_flight_held_solutions_stay_success() -> None:
    exact = inference_from_core(
        _core_row(status="exact", solution_count=1, solutions=[{"objectiveValue": 1}]),
        player_id=6,
    )
    in_flight = inference_from_core(
        _core_row(
            status="pending",
            solution_count=1,
            is_complete=False,
            solutions=[{"objectiveValue": 1}],
        ),
        player_id=7,
    )
    assert exact["displayStatus"] == "success"
    assert in_flight["displayStatus"] == "success"
