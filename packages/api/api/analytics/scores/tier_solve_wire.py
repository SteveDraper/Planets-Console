"""Job-wire key constants for scores ``tier_solve``.

Orchestration-plane schema shared by the parent builder. ``orchestrationSkip`` /
``evidenceClosed`` complete on the parent. Process SAT is a SAT-session worker;
the parent Solve seam is not wired, so process dispatch fails loud.
"""

from __future__ import annotations

from api.compute.wire import WIRE_ORCHESTRATION_SKIP as WIRE_ORCHESTRATION_SKIP

WIRE_EVIDENCE_CLOSED = "evidenceClosed"
WIRE_RUN_ID = "runId"
WIRE_LADDER_STATE = "ladderState"
WIRE_GAME_ID = "gameId"
WIRE_PERSPECTIVE = "perspective"
WIRE_TURN = "turn"
WIRE_PLAYER_ID = "playerId"
