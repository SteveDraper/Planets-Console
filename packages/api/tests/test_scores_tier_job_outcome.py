"""The tier job contract: a run always has a ladder, and every terminal status is durable."""

from __future__ import annotations

from types import ModuleType

import pytest
from api.analytics.military_score_inference import (
    inference_api_payload,
    solver,
    uncharacterized_roster,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.durable_turn_evidence import (
    DURABLE_TURN_EVIDENCE_ROW_STATUSES,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.tier_row_run_registry import new_tier_row_run

# Every module that defines a row status a tier terminal can carry.
_ROW_STATUS_MODULES: tuple[ModuleType, ...] = (
    solver,
    inference_api_payload,
    uncharacterized_roster,
)


def _row_statuses(module: ModuleType) -> dict[str, str]:
    return {
        name: value
        for name, value in vars(module).items()
        if name.startswith("STATUS_") and isinstance(value, str)
    }


def _session(sample_turn) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def test_a_row_run_cannot_be_built_without_a_ladder(sample_turn) -> None:
    with pytest.raises(TypeError):
        RowRun(_session(sample_turn))  # type: ignore[call-arg]


def test_new_tier_row_run_seeds_its_ladder_and_keeps_the_orchestration(sample_turn) -> None:
    session = _session(sample_turn)
    score = sample_turn.scores[0]
    orchestration = InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_SPLIT,
        row_score=score,
        row_turn=sample_turn,
        solve_score=score,
        solve_turn=sample_turn,
        segments=(),
    )

    run = new_tier_row_run(session, orchestration=orchestration)

    assert run.session is session
    assert run.orchestration is orchestration
    assert run.ladder_state.resolved_mask is session.resolved_mask
    assert run.ladder_state.ladder_complete is False


@pytest.mark.parametrize("module", _ROW_STATUS_MODULES, ids=lambda module: module.__name__)
def test_every_row_status_a_terminal_can_carry_closes_turn_evidence(module) -> None:
    statuses = _row_statuses(module)
    assert statuses, f"{module.__name__} defines no STATUS_ constants"
    not_durable = {
        name: value
        for name, value in statuses.items()
        if value not in DURABLE_TURN_EVIDENCE_ROW_STATUSES
    }
    assert not_durable == {}
