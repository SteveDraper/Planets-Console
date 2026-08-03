"""Validate and persist homeworld assertions; rematerialize candidate view (#37)."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.homeworld_locator.assertions import (
    revoke_location_assertion,
    revoke_ownership_assertion,
    upsert_location_assertion,
    upsert_ownership_assertion,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.sector_overlays import homeworld_layout_asset_category
from api.analytics.homeworld_locator.types import HomeworldLocatorGameState
from api.analytics.turn_roster import players_by_id
from api.concepts.warp_well import planet_is_planetoid
from api.errors import NotFoundError, ValidationError
from api.models.game import TurnInfo
from api.transport.homeworld_assertions import (
    HomeworldAssertionAction,
    HomeworldAssertionAxis,
)


def homeworld_sectors_exist(turn: TurnInfo) -> bool:
    """True when ownership asserts are sector-keyed for this shell turn.

    Matches materialize sector partition eligibility (circular + round +
    epic|standard layout asset category with at least two players), without
    requiring a viewpoint pin so API keying stays stable before pin resolve.
    """
    player_count = len(players_by_id(turn))
    if player_count < 2:
        return False
    return homeworld_layout_asset_category(turn, player_count=player_count) is not None


class HomeworldAssertionService:
    """Thin assertion/refresh service: validate, persist game-global asserts, rematerialize."""

    def __init__(
        self,
        *,
        persistence: HomeworldLocatorPersistenceService,
        load_turn: Callable[[int], TurnInfo | None],
        game_id: int,
        perspective: int,
        rematerialize: Callable[[int], dict],
    ) -> None:
        self._persistence = persistence
        self._load_turn = load_turn
        self._game_id = game_id
        self._perspective = perspective
        self._rematerialize = rematerialize

    def upsert_location_assertion(self, *, planet_id: int, turn_number: int) -> dict:
        turn = self._require_turn(turn_number)
        self._require_traditional_planet(turn, planet_id)
        state = self._load_or_empty_state()
        updated = upsert_location_assertion(state, planet_id=planet_id, turn=turn_number)
        self._persistence.put_game_state(self._game_id, updated)
        return self._rematerialize(turn_number)

    def revoke_location_assertion(self, *, planet_id: int, turn_number: int) -> dict:
        self._require_turn(turn_number)
        if planet_id < 1:
            raise ValidationError("planet_id must be >= 1")
        state = self._load_or_empty_state()
        updated = revoke_location_assertion(state, planet_id=planet_id)
        self._persistence.put_game_state(self._game_id, updated)
        return self._rematerialize(turn_number)

    def upsert_ownership_assertion(
        self,
        *,
        owner_slot: int,
        turn_number: int,
        planet_id: int | None,
        sector_index: int | None,
    ) -> dict:
        turn = self._require_turn(turn_number)
        sectors_exist = homeworld_sectors_exist(turn)
        if not sectors_exist and planet_id is not None:
            self._require_traditional_planet(turn, planet_id)
        try:
            updated = upsert_ownership_assertion(
                self._load_or_empty_state(),
                owner_slot=owner_slot,
                turn=turn_number,
                sector_index=sector_index,
                planet_id=planet_id,
                sectors_exist=sectors_exist,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._persistence.put_game_state(self._game_id, updated)
        return self._rematerialize(turn_number)

    def revoke_ownership_assertion(
        self,
        *,
        owner_slot: int,
        turn_number: int,
        planet_id: int | None,
        sector_index: int | None,
    ) -> dict:
        turn = self._require_turn(turn_number)
        sectors_exist = homeworld_sectors_exist(turn)
        try:
            updated = revoke_ownership_assertion(
                self._load_or_empty_state(),
                owner_slot=owner_slot,
                sector_index=sector_index,
                planet_id=planet_id,
                sectors_exist=sectors_exist,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._persistence.put_game_state(self._game_id, updated)
        return self._rematerialize(turn_number)

    def refresh(self, *, turn_number: int) -> dict:
        """Wipe machine homeworld state for the shell perspective, then ensure rebuild."""
        self._require_turn(turn_number)
        self._persistence.clear_baseline_for_recompute(self._game_id, self._perspective)
        return self._rematerialize(turn_number)

    def apply_assertion(
        self,
        *,
        axis: HomeworldAssertionAxis,
        action: HomeworldAssertionAction,
        turn_number: int,
        planet_id: int | None = None,
        sector_index: int | None = None,
        owner_slot: int | None = None,
    ) -> dict:
        # Defense in depth for non-HTTP callers that bypass transport validation.
        if axis not in {"location", "ownership"}:
            raise ValidationError("axis must be 'location' or 'ownership'")
        if action not in {"upsert", "revoke"}:
            raise ValidationError("action must be 'upsert' or 'revoke'")
        if axis == "location":
            if planet_id is None:
                raise ValidationError("location assertion requires planetId")
            if action == "upsert":
                return self.upsert_location_assertion(
                    planet_id=planet_id,
                    turn_number=turn_number,
                )
            return self.revoke_location_assertion(
                planet_id=planet_id,
                turn_number=turn_number,
            )
        if owner_slot is None:
            raise ValidationError("ownership assertion requires ownerSlot")
        if action == "upsert":
            return self.upsert_ownership_assertion(
                owner_slot=owner_slot,
                turn_number=turn_number,
                planet_id=planet_id,
                sector_index=sector_index,
            )
        return self.revoke_ownership_assertion(
            owner_slot=owner_slot,
            turn_number=turn_number,
            planet_id=planet_id,
            sector_index=sector_index,
        )

    def _require_turn(self, turn_number: int) -> TurnInfo:
        if turn_number < 1:
            raise ValidationError("turn_number must be >= 1")
        turn = self._load_turn(turn_number)
        if turn is None:
            raise NotFoundError(
                f"turn {turn_number} is not stored for game {self._game_id} "
                f"perspective {self._perspective}"
            )
        return turn

    def _require_traditional_planet(self, turn: TurnInfo, planet_id: int) -> None:
        if planet_id < 1:
            raise ValidationError("planet_id must be >= 1")
        planet = next((row for row in turn.planets if row.id == planet_id), None)
        if planet is None:
            raise ValidationError(f"planet {planet_id} is not present on the shell turn")
        if planet_is_planetoid(planet):
            raise ValidationError(
                f"planet {planet_id} is a planetoid; homeworld location asserts "
                "require a traditional planet"
            )

    def _load_or_empty_state(self) -> HomeworldLocatorGameState:
        existing = self._persistence.get_game_state(self._game_id)
        if existing is not None:
            return existing
        return HomeworldLocatorGameState(
            candidates=(),
            baseline_turn=0,
            baseline_degraded=False,
        )


__all__ = [
    "HomeworldAssertionService",
    "homeworld_sectors_exist",
]
