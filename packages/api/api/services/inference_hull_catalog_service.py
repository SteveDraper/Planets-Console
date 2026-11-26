"""Read and write per-player inference hull catalog mask overrides."""

from __future__ import annotations

from api.analytics.military_score_inference.hull_catalog_mask import (
    ResolvedHullCatalogMask,
    hull_names_by_id,
    resolve_hull_catalog_mask,
)
from api.analytics.scores.hull_mask_overrides import HullMaskOverrides
from api.errors import ValidationError
from api.services.turn_load_service import TurnLoadService


class InferenceHullCatalogService:
    """Hull catalog mask payloads and edits; the stored overrides live in ``HullMaskOverrides``."""

    def __init__(self, turns: TurnLoadService, mask_overrides: HullMaskOverrides) -> None:
        self._turns = turns
        self._mask_overrides = mask_overrides

    def resolve_mask_for_player(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> ResolvedHullCatalogMask:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        return self._mask_overrides.effective_mask(turn, game_id, player_id)

    def hull_catalog_mask_payload(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        resolved = self._mask_overrides.effective_mask(turn, game_id, player_id)
        user_override = resolved.user_enabled_hull_ids
        names = hull_names_by_id(turn)
        master_entries = [
            {
                "hullId": hull_id,
                "name": names.get(hull_id, f"Hull {hull_id}"),
                "defaultEnabled": hull_id in resolved.default_enabled_hull_ids,
                "userEnabled": (
                    hull_id in user_override
                    if user_override is not None
                    else hull_id in resolved.default_enabled_hull_ids
                ),
                "effectiveEnabled": hull_id in resolved.effective_enabled_hull_ids,
            }
            for hull_id in sorted(resolved.master_hull_ids)
        ]
        return {
            "gameId": game_id,
            "playerId": player_id,
            "perspective": perspective,
            "turn": turn_number,
            "campaignMode": turn.settings.campaignmode,
            "raceId": resolved.race_id,
            "raceName": resolved.race_name,
            "masterCatalog": master_entries,
            "defaultEnabledHullIds": sorted(resolved.default_enabled_hull_ids),
            "userEnabledHullIds": (sorted(user_override) if user_override is not None else None),
            "effectiveEnabledHullIds": sorted(resolved.effective_enabled_hull_ids),
            "hasUserOverride": resolved.has_user_override,
        }

    def put_user_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        enabled_hull_ids: list[int],
    ) -> dict[str, object]:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        resolved = resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=None)
        master = resolved.master_hull_ids
        invalid = [hull_id for hull_id in enabled_hull_ids if hull_id not in master]
        if invalid:
            raise ValidationError(f"hull ids not in race master catalog: {sorted(invalid)}")
        self._mask_overrides.change(game_id, player_id, frozenset(enabled_hull_ids))
        return self.hull_catalog_mask_payload(game_id, perspective, turn_number, player_id)

    def reset_user_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        self._mask_overrides.change(game_id, player_id, None)
        return self.hull_catalog_mask_payload(game_id, perspective, turn_number, player_id)
