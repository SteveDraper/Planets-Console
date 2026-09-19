"""Storage-rebuild SAT leaf for scores ``tier_solve``.

Spawn imports this module (solver + storage + codec), not ``server.app``.
The child never looks up ``RowRun`` and does not map orchestrator outcomes.
It returns a pickle-safe snapshot (echoed ``runId`` plus catalog-free ladder
state). The parent maps that snapshot to ``StepResult``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
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
from api.compute.wire import WIRE_ORCHESTRATION_SKIP
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


def run_scores_tier_solve_leaf(job_wire: dict[str, Any]) -> dict[str, object]:
    """Run one scores inference tier from a pickle-safe job wire.

    Skip sentinels complete on the orchestration plane and must not reach this
    leaf. Open-evidence wires load the turn from ``storageRoot`` and rebuild the
    inference problem; they do not consult the parent ``RowRun`` or choose
    continue/persist/waiting_deps.
    """
    if job_wire.get(WIRE_ORCHESTRATION_SKIP) is True:
        raise RuntimeError(
            "scores tier_solve leaf must not receive orchestrationSkip; "
            "skip sentinels complete on the orchestration plane"
        )

    state = job_wire.get(WIRE_LADDER_STATE)
    if not isinstance(state, PolicyLadderState):
        return _payload_with_echoed_run_id(job_wire)

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
    return _payload_with_echoed_run_id(
        job_wire,
        {WIRE_LADDER_STATE: process_safe_ladder_state(state)},
    )


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
) -> dict[str, object]:
    """Copy the parent ``runId`` onto the snapshot when the job wire has one.

    The leaf never looks up ``RowRun``; the parent mapper identifies the live
    shell from this echoed id.
    """
    payload: dict[str, object] = dict(extra) if extra is not None else {}
    run_id = job_wire.get(WIRE_RUN_ID)
    if isinstance(run_id, str):
        payload[WIRE_RUN_ID] = run_id
    return payload
