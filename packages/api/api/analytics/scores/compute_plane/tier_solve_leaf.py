"""Storage-rebuild SAT leaf for scores ``tier_solve``.

Spawn imports this module (solver + storage + codec), not ``server.app``.
The child never looks up ``RowRun``. It echoes the job-wire ``runId`` onto
result payloads; the parent applies those payloads to ladder state on persist
and on the next ``tier_solve`` wire build.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    fleet_torp_input_status_diagnostics,
)
from api.analytics.military_score_inference.row_complete_factory import (
    row_complete_from_ladder_finalize,
)
from api.analytics.scores.export_precedence import is_durable_turn_evidence_row_status
from api.analytics.scores.tier_solve_wire import (
    WIRE_GAME_ID,
    WIRE_LADDER_STATE,
    WIRE_OBSERVATION,
    WIRE_PERSPECTIVE,
    WIRE_RUN_ID,
    WIRE_STORAGE_ROOT,
    WIRE_TIME_LIMIT_SECONDS,
    WIRE_TURN,
)
from api.compute.wire import WIRE_ORCHESTRATION_SKIP, StepResult
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json
from api.storage import open_file_backend


def process_safe_ladder_state(state: PolicyLadderState) -> PolicyLadderState:
    """Copy ladder progress without live catalog, SAT model, or twin asset.

    The child rebuilds those from storage and the policy step. Sharing the
    in-memory catalog would pickle tens of thousands of combos onto the job wire.
    """
    return replace(
        state,
        catalog=None,
        problem=None,
        hull_collision_twins=None,
        hull_collision_twins_loaded=False,
    )


def run_scores_tier_solve_leaf(job_wire: dict[str, Any]) -> StepResult:
    """Run one scores inference tier from a pickle-safe job wire.

    Skip sentinels complete on the orchestration plane and must not reach this
    leaf. Open-evidence wires load the turn from ``storageRoot`` and rebuild the
    inference problem; they do not consult the parent ``RowRun`` registry.
    """
    if job_wire.get(WIRE_ORCHESTRATION_SKIP) is True:
        raise RuntimeError(
            "scores tier_solve leaf must not receive orchestrationSkip; "
            "skip sentinels complete on the orchestration plane"
        )

    state = job_wire.get(WIRE_LADDER_STATE)
    if not isinstance(state, PolicyLadderState):
        return StepResult(
            outcome="waiting_deps",
            payload=_payload_with_echoed_run_id(job_wire),
        )

    observation = job_wire.get(WIRE_OBSERVATION)
    if not isinstance(observation, InferenceObservation):
        raise TypeError("scores tier_solve leaf requires InferenceObservation on the job wire")

    turn = _load_turn_from_job_wire(job_wire)
    time_limit = job_wire.get(WIRE_TIME_LIMIT_SECONDS)
    time_limit_seconds = float(time_limit) if isinstance(time_limit, (int, float)) else None

    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=time_limit_seconds,
    )
    return _step_result_from_ladder_state(job_wire, state, observation, turn)


def _load_turn_from_job_wire(job_wire: dict[str, Any]) -> TurnInfo:
    storage_root = job_wire.get(WIRE_STORAGE_ROOT)
    if not isinstance(storage_root, str) or storage_root == "":
        raise TypeError("scores tier_solve leaf requires string storageRoot")
    game_id = job_wire.get(WIRE_GAME_ID)
    perspective = job_wire.get(WIRE_PERSPECTIVE)
    turn_number = job_wire.get(WIRE_TURN)
    if not isinstance(game_id, int):
        raise TypeError("scores tier_solve leaf requires integer gameId")
    if not isinstance(perspective, int):
        raise TypeError("scores tier_solve leaf requires integer perspective")
    if not isinstance(turn_number, int):
        raise TypeError("scores tier_solve leaf requires integer turn")
    storage = open_file_backend(Path(storage_root))
    payload = storage.get(f"games/{game_id}/{perspective}/turns/{turn_number}")
    if not isinstance(payload, dict):
        raise TypeError("scores tier_solve leaf turn document must be a JSON object")
    return turn_info_from_json(payload)


def _payload_with_echoed_run_id(
    job_wire: dict[str, Any],
    extra: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Copy the parent ``runId`` onto the result payload when the job wire has one.

    The leaf never looks up ``RowRun``; persist and parent apply identify the
    live shell from this echoed id.
    """
    payload: dict[str, object] = dict(extra) if extra is not None else {}
    run_id = job_wire.get(WIRE_RUN_ID)
    if isinstance(run_id, str):
        payload[WIRE_RUN_ID] = run_id
    return payload if payload else None


def _step_result_from_ladder_state(
    job_wire: dict[str, Any],
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> StepResult:
    if not state.ladder_complete:
        return StepResult(
            outcome="continue",
            payload=_payload_with_echoed_run_id(
                job_wire,
                {WIRE_LADDER_STATE: process_safe_ladder_state(state)},
            ),
        )

    result, catalog, problem, policy_steps_attempted, step_diagnostics = (
        finalize_policy_ladder_result(state, observation, turn)
    )
    row_complete = row_complete_from_ladder_finalize(
        result,
        catalog,
        problem,
        policy_steps_attempted,
        step_diagnostics,
        observation=observation,
        turn=turn,
        extra_diagnostics=fleet_torp_input_status_diagnostics(None),
        resolved_mask=state.resolved_mask,
    )
    payload = _payload_with_echoed_run_id(
        job_wire,
        {
            WIRE_LADDER_STATE: process_safe_ladder_state(state),
            "rowComplete": row_complete,
        },
    )
    status = row_complete.wire_payload.status
    if is_durable_turn_evidence_row_status(status):
        return StepResult(outcome="persist", payload=payload)
    return StepResult(outcome="waiting_deps", payload=payload)
