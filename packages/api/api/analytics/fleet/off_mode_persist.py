"""Fleet persist decisions for an off-mode job.

The merge generation rule lives in ``api.analytics.off_mode``. This module
refuses a fleet write whose job epoch is stale, and loads the stored
generation that rule needs for an observation merge.
"""

from __future__ import annotations

from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.fleet.types import StampCurrentEvidenceMark
from api.analytics.off_mode import off_mode_merge_generation
from api.analytics.off_mode_wire import OffModeWireFields
from api.compute.scope import ComputeScope
from api.exceptions import DiscardedWorkRefused, ValidationError


def refuse_stale_fleet_epoch(
    services: FleetComputeServices,
    scope: ComputeScope,
    fields: OffModeWireFields,
) -> None:
    """Refuse a fleet persist whose job epoch is not the player's current epoch.

    Fast fail before the ledger is built. ``put_ledger`` repeats the compare
    under the generation lock when it chooses the generation to write.
    ``playerInvalidationGeneration`` is required. A missing value raises
    ``ValidationError``. A present non-integer is already rejected by
    ``parse_off_mode_wire``. When the player id is concrete and the current
    epoch differs, the write raises ``DiscardedWorkRefused``.
    """
    expected = fields.player_invalidation_generation
    if expected is None:
        raise ValidationError("fleet persist wire requires integer playerInvalidationGeneration")
    if not isinstance(scope.player_id, int):
        return
    current = services.persistence.player_invalidation_generation(
        scope.game_id,
        scope.perspective,
        scope.player_id,
    )
    if current == expected:
        return
    raise DiscardedWorkRefused(
        f"fleet persist refused for game {scope.game_id} perspective {scope.perspective} "
        f"player {scope.player_id} turn {scope.turn}: in-flight work cannot stamp the new mark"
    )


def job_player_epoch(fields: OffModeWireFields) -> int:
    """Player epoch carried on a fleet persist wire.

    ``refuse_stale_fleet_epoch`` rejects a missing epoch. The ledger write
    compares this value under the generation lock.
    """
    epoch = fields.player_invalidation_generation
    if isinstance(epoch, bool) or not isinstance(epoch, int):
        raise ValidationError("fleet persist wire requires integer playerInvalidationGeneration")
    return epoch


def observation_merge_generation(
    services: FleetComputeServices,
    scope: ComputeScope,
    fields: OffModeWireFields,
) -> int | StampCurrentEvidenceMark:
    """Generation this observation merge writes.

    ``STAMP_CURRENT_EVIDENCE_MARK`` stamps the current mark. An int is the
    generation kept on the open turn. The generation comes from
    ``off_mode_merge_generation``. An open turn without a carried
    ``backfillEarlierTurns`` value is a ``ValidationError`` and does not read
    storage. Otherwise that carried value is used as-is, and a wire with no
    choice is backfill off. The merge does not read the mark or the stored
    backfill record. The stored generation is loaded only when the wire
    carries a submission root.
    """
    if not isinstance(scope.player_id, int) or not isinstance(scope.turn, int):
        raise ValueError("fleet observation merge requires concrete player_id and turn")
    open_turn = fields.open_turn
    carried_backfill = fields.backfill_earlier_turns
    if open_turn is not None and carried_backfill is None:
        raise ValidationError(
            "fleet observation merge requires backfillEarlierTurns when openTurn is set"
        )
    backfill_enabled = False if carried_backfill is None else carried_backfill
    stored_generation: int | None = None
    if open_turn is not None:
        stored = services.persistence.get_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
        )
        if stored is not None:
            stored_generation = stored.evidence_generation
    return off_mode_merge_generation(
        backfill_enabled=backfill_enabled,
        open_turn=open_turn,
        is_catch_up=fields.catch_up,
        host_turn=scope.turn,
        stored_generation=stored_generation,
    )
