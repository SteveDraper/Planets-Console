"""Read and write per-player inference hull catalog mask overrides."""

from __future__ import annotations

from api.analytics.military_score_inference.hull_catalog_mask import (
    hull_names_by_id,
    resolve_hull_catalog_mask,
)
from api.analytics.scores import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.errors import NotFoundError, ValidationError
from api.serialization.inference_hull_catalog import (
    InferenceHullCatalogMaskOverride,
    inference_hull_catalog_mask_override_from_json,
    inference_hull_catalog_mask_override_to_json,
)
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend

_INFERENCE_HULL_CATALOG_MASKS_KEY = "inference_hull_catalog_masks"


class InferenceHullCatalogService:
    def __init__(self, storage: StorageBackend, turns: TurnLoadService) -> None:
        self._storage = storage
        self._turns = turns

    def _mask_store_key(self, game_id: int, player_id: int) -> str:
        return (
            f"games/{game_id}/analytics/{SCORES_ANALYTIC_ID}/"
            f"{_INFERENCE_HULL_CATALOG_MASKS_KEY}/{player_id}"
        )

    def _load_user_override(self, game_id: int, player_id: int) -> frozenset[int] | None:
        try:
            data = self._storage.get(self._mask_store_key(game_id, player_id))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("stored hull catalog mask override must be a JSON object")
        override = inference_hull_catalog_mask_override_from_json(data)
        return frozenset(override.enabled_hull_ids)

    def resolve_mask_for_player(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ):
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        return self.resolve_mask_for_player_on_turn(turn, game_id, player_id)

    def resolve_mask_for_player_on_turn(
        self,
        turn,
        game_id: int,
        player_id: int,
    ):
        user_override = self._load_user_override(game_id, player_id)
        return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=user_override)

    def hull_catalog_mask_payload(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        user_override = self._load_user_override(game_id, player_id)
        resolved = resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=user_override)
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
        override = InferenceHullCatalogMaskOverride(enabled_hull_ids=sorted(enabled_hull_ids))
        self._storage.put(
            self._mask_store_key(game_id, player_id),
            inference_hull_catalog_mask_override_to_json(override),
        )
        return self.hull_catalog_mask_payload(game_id, perspective, turn_number, player_id)

    def reset_user_mask(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        key = self._mask_store_key(game_id, player_id)
        try:
            self._storage.delete(key)
        except NotFoundError:
            pass
        return self.hull_catalog_mask_payload(game_id, perspective, turn_number, player_id)
