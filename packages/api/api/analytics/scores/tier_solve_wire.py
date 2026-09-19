"""Job-wire key constants for scores ``tier_solve``.

Orchestration-plane schema shared by the parent builder and the pickle-safe
SAT leaf. ``orchestrationSkip`` / ``evidenceClosed`` complete on the parent;
the leaf reads storage-rebuild fields only and must not treat skip as success.
"""

from __future__ import annotations

from api.compute.wire import WIRE_ORCHESTRATION_SKIP as WIRE_ORCHESTRATION_SKIP

WIRE_EVIDENCE_CLOSED = "evidenceClosed"
WIRE_STORAGE_ROOT = "storageRoot"
WIRE_LADDER_STATE = "ladderState"
WIRE_OBSERVATION = "observation"
WIRE_TIME_LIMIT_SECONDS = "timeLimitSeconds"
WIRE_GAME_ID = "gameId"
WIRE_PERSPECTIVE = "perspective"
WIRE_TURN = "turn"
WIRE_PLAYER_ID = "playerId"
