"""In-memory cache for turn loads during prior mining."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.models.game import TurnInfo
from api.services.turn_load_service import TurnLoadService


@dataclass
class MiningTurnCache:
    """Avoid repeated storage listings and JSON deserialization within one game pass."""

    turn_load: TurnLoadService
    _stored_turn_numbers: dict[tuple[int, int], frozenset[int]] = field(default_factory=dict)
    _turn_info: dict[tuple[int, int, int], TurnInfo] = field(default_factory=dict)
    _perspectives_at_turn: dict[tuple[int, int], frozenset[int]] = field(default_factory=dict)

    def stored_turn_numbers(self, game_id: int, perspective: int) -> frozenset[int]:
        key = (game_id, perspective)
        cached = self._stored_turn_numbers.get(key)
        if cached is None:
            cached = frozenset(self.turn_load.list_stored_turn_numbers(game_id, perspective))
            self._stored_turn_numbers[key] = cached
        return cached

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        key = (game_id, perspective, turn_number)
        cached = self._turn_info.get(key)
        if cached is None:
            cached = self.turn_load.get_turn_info(game_id, perspective, turn_number)
            self._turn_info[key] = cached
        return cached

    def perspectives_at_turn(self, game_id: int, turn_number: int) -> frozenset[int]:
        key = (game_id, turn_number)
        cached = self._perspectives_at_turn.get(key)
        if cached is None:
            cached = frozenset(self.turn_load.list_stored_turn_perspectives(game_id, turn_number))
            self._perspectives_at_turn[key] = cached
        return cached
