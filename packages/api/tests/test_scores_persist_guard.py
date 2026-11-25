"""A scores row persist is refused when its claim epoch is no longer current.

The orchestrator checks the epoch before it calls ``persist``, under its own
lock, then releases that lock. The guard repeats the check under the
player's hull mask key lock and holds it across the write, so a mask change
cannot land between the check and the write.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores import compute_orchestration
from api.analytics.scores.compute_orchestration import (
    CLAIM_EPOCH_WIRE_FIELD,
    SCORES_PERSISTENCE_POLICY,
    ClaimEpochPersistGuard,
)
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.hull_mask_overrides import HullMaskOverrides
from api.exceptions import DiscardedWorkRefused, ValidationError
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.scores_exports_helpers import GAME_ID
from tests.scores_ladder_helpers import durable_row_complete

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

PERSPECTIVE = 1
HOST_TURN = 111
PLAYER_ID = 3


class _RecordingGuard:
    """A guard that admits or refuses, and records when its hold is entered and left."""

    def __init__(self, *, admits: bool) -> None:
        self.admits = admits
        self.events: list[str] = []

    @contextmanager
    def admitted(self) -> Iterator[None]:
        self.events.append("enter")
        try:
            if not self.admits:
                raise DiscardedWorkRefused("stale claim epoch")
            yield
        finally:
            self.events.append("exit")


def _row_complete():
    return durable_row_complete("guarded").row_complete


def _persist(persistence: InferenceRowPersistenceService, guard) -> None:
    persistence.persist_row_complete_guarded(
        _row_complete(),
        guard=guard,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        host_turn=HOST_TURN,
        player_id=PLAYER_ID,
        on_walk=False,
    )


def test_a_refusing_guard_writes_nothing_and_notifies_nothing():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    notified: list[int] = []
    persistence.on_row_persisted = lambda *args, **_kwargs: notified.append(args[3])
    guard = _RecordingGuard(admits=False)

    with pytest.raises(DiscardedWorkRefused):
        _persist(persistence, guard)

    assert persistence.get_row(GAME_ID, PERSPECTIVE, HOST_TURN, PLAYER_ID) is None
    assert notified == []


def test_an_admitted_write_lands_inside_the_hold_and_notifies_after_it():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    guard = _RecordingGuard(admits=True)
    persistence.on_row_persisted = lambda *_args, **_kwargs: guard.events.append("notify")

    _persist(persistence, guard)

    stored = persistence.get_row(GAME_ID, PERSPECTIVE, HOST_TURN, PLAYER_ID)
    assert stored is not None and stored.status == STATUS_EXACT
    assert guard.events == ["enter", "exit", "notify"]


def _claim_epoch_guard(ladder, claim_epoch: int) -> ClaimEpochPersistGuard:
    return ClaimEpochPersistGuard(
        ctx=ladder.ctx,
        scope=ladder.scope,
        claim_epoch=claim_epoch,
        mask_overrides=resolve_scores_services(ladder.ctx).mask_overrides,
    )


def test_the_claim_epoch_guard_refuses_after_a_mask_change(ladder):
    epoch = SCORES_PERSISTENCE_POLICY.invalidation_generation(ladder.ctx, ladder.scope)
    guard = _claim_epoch_guard(ladder, epoch)
    with guard.admitted():
        pass

    ladder.change_mask()

    with pytest.raises(DiscardedWorkRefused), guard.admitted():
        pass


def test_a_mask_change_waits_for_an_admitted_write(ladder):
    epoch = SCORES_PERSISTENCE_POLICY.invalidation_generation(ladder.ctx, ladder.scope)
    overrides: HullMaskOverrides = resolve_scores_services(ladder.ctx).mask_overrides
    changed = threading.Event()

    def change() -> None:
        ladder.change_mask()
        changed.set()

    with _claim_epoch_guard(ladder, epoch).admitted():
        worker = threading.Thread(target=change)
        worker.start()
        assert not changed.wait(timeout=0.2)
        assert overrides.revision(GAME_ID, ladder.player_id) == 0
    worker.join(timeout=5)
    assert changed.is_set()


def test_a_mask_change_after_the_orchestrators_check_refuses_the_write(ladder):
    ladder.submit()
    result_wire = ladder.execute_tier(durable_row_complete("built from the old mask"))
    decide = compute_orchestration.decide_scores_row_persist

    def change_mask_then_decide(run_id: str):
        ladder.change_mask()
        return decide(run_id)

    with patch.object(
        compute_orchestration, "decide_scores_row_persist", side_effect=change_mask_then_decide
    ):
        ladder.complete_tier(result_wire)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert ladder.persisted_summary() is None
    assert node.state != "failed", node.error
    assert node.state != "complete"


def test_a_persist_wire_without_a_claim_epoch_is_rejected(ladder):
    ladder.submit()
    result_wire = ladder.execute_tier(durable_row_complete("no claim epoch"))
    payload = dict(result_wire.payload)
    del payload[CLAIM_EPOCH_WIRE_FIELD]

    with pytest.raises(ValidationError, match=CLAIM_EPOCH_WIRE_FIELD):
        SCORES_PERSISTENCE_POLICY.persist(ladder.ctx, ladder.scope, payload)
