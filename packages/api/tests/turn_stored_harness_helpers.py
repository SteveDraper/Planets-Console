"""Shared pieces of the turn-stored nesting harnesses.

Both harnesses run the real service stack on a memory backend with a fake
Planets.nu client, so every turn a fill fetches goes through
``TurnLoadService.ensure_turn_loaded`` and the stack's turn-stored hook. Fetch
nesting is counted as 1 plus the hook frames active on the fetching thread.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from api.compute.turn_cache import clear_process_turn_info_cache
from api.models.game import TurnInfo
from api.models.player import Score
from api.models.turn_write import TurnWrite
from api.planets_nu import PlanetsNuClient
from api.serialization.turn import turn_info_to_json
from api.services.stack import ServiceStack, build_service_stack
from api.services.turn_load_service import TurnLoadService
from api.services.turn_stored_fan_out import TurnStoredFanOut
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.game_info_update import RefreshGameInfoParams

GAME_ID = 628580
PERSPECTIVE = 1
USERNAME = "player1"
DEFAULT_RECURSION_LIMIT = 1000
ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def stack_depth() -> int:
    """Frames on the caller's stack."""
    depth = 0
    frame = sys._getframe(1)
    while frame is not None:
        depth += 1
        frame = frame.f_back
    return depth


class HookFrames(threading.local):
    """Turn-stored hook frames active on the current thread."""

    def __init__(self) -> None:
        self.active = 0


def count_hook_frames(hook_frames: HookFrames, monkeypatch) -> None:
    """Count hook frames per thread; patch before the stack builds."""
    real_on_turn_stored = TurnStoredFanOut.on_turn_stored

    def on_turn_stored(self: TurnStoredFanOut, write: TurnWrite) -> None:
        hook_frames.active += 1
        try:
            real_on_turn_stored(self, write)
        finally:
            hook_frames.active -= 1

    monkeypatch.setattr(TurnStoredFanOut, "on_turn_stored", on_turn_stored)


def without_scoreboard_deltas(score: Score) -> Score:
    return replace(
        score, **{field.name: 0 for field in fields(score) if field.name.endswith("change")}
    )


@dataclass
class TurnSource:
    """The harness turns: the sample turn at each turn number.

    ``accelerated_turns`` sets the accelerated start; with ``quiet_scoreboard``
    no scoreboard row has deltas, so every scores row solves in one cheap tier.
    """

    sample_turn: TurnInfo
    accelerated_turns: int = 0
    quiet_scoreboard: bool = False

    def turn_at(self, turn_number: int) -> TurnInfo:
        sample = self.sample_turn
        scores = sample.scores
        if self.quiet_scoreboard:
            scores = [without_scoreboard_deltas(score) for score in scores]
        return replace(
            sample,
            settings=replace(
                sample.settings, turn=turn_number, acceleratedturns=self.accelerated_turns
            ),
            game=replace(sample.game, turn=turn_number),
            scores=scores,
        )

    def store(self, storage: MemoryAssetBackend, turn_numbers) -> None:
        for turn_number in turn_numbers:
            storage.put(
                TurnLoadService.turn_store_key(GAME_ID, PERSPECTIVE, turn_number),
                turn_info_to_json(self.turn_at(turn_number)),
            )


@dataclass(frozen=True)
class Fetch:
    turn: int
    nesting: int
    stack_depth: int
    thread: int


@dataclass
class FakePlanetsNu:
    """A Planets.nu client that serves the harness turns and records each fetch."""

    hook_frames: HookFrames
    turns: TurnSource
    fetches: list[Fetch] = field(default_factory=list)
    failing_turns: set[int] = field(default_factory=set)

    def load_turn(self, *, game_id: int, turn: int | None, player_id: int, api_key=None):
        assert turn is not None
        self.fetches.append(
            Fetch(
                turn=turn,
                nesting=1 + self.hook_frames.active,
                stack_depth=stack_depth(),
                thread=threading.get_ident(),
            )
        )
        if turn in self.failing_turns:
            return {"success": False, "error": "upstream unavailable"}
        return {"success": True, "rst": turn_info_to_json(self.turns.turn_at(turn))}

    def fetched_turns(self) -> list[int]:
        return [fetch.turn for fetch in self.fetches]

    def nesting_by_turn(self) -> dict[int, int]:
        return {fetch.turn: fetch.nesting for fetch in self.fetches}


@dataclass(frozen=True)
class StoredGame:
    """The service stack over a memory backend holding the sample game and a login key."""

    storage: MemoryAssetBackend
    stack: ServiceStack
    turns: TurnSource
    planets: FakePlanetsNu

    def store_turns(self, turn_numbers) -> None:
        self.turns.store(self.storage, turn_numbers)

    def forget_turns(self, turn_numbers) -> None:
        """Remove stored turns, so a fill or a store must fetch them again."""
        for turn_number in turn_numbers:
            if self.stack.turns.is_turn_stored(GAME_ID, PERSPECTIVE, turn_number):
                self.storage.delete(
                    TurnLoadService.turn_store_key(GAME_ID, PERSPECTIVE, turn_number)
                )
        clear_process_turn_info_cache()

    def store_turn_outside_any_root_plan(self, turn_number: int) -> None:
        """Store a turn the way Load all and the MCP turn-ensure do."""
        self.stack.turns.ensure_turn_loaded(
            GAME_ID,
            PERSPECTIVE,
            turn_number,
            RefreshGameInfoParams(username=USERNAME),
            self.planets,
        )

    def query_context(self, turn_number: int, **kwargs):
        """The login-backed query context the stack builds for ``turn_number``."""
        return self.stack.analytics.export_query_context(
            GAME_ID, PERSPECTIVE, turn_number, username=USERNAME, **kwargs
        )


def build_stored_game(turns: TurnSource, monkeypatch) -> StoredGame:
    """Build the stack with a fake Planets.nu client and a counted turn-stored hook."""
    hook_frames = HookFrames()
    count_hook_frames(hook_frames, monkeypatch)
    storage = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put(f"games/{GAME_ID}/info", json.load(handle))
    storage.put(f"credentials/accounts/{USERNAME}/api_key", "k")
    planets = FakePlanetsNu(hook_frames=hook_frames, turns=turns)
    monkeypatch.setattr(PlanetsNuClient, "from_config", staticmethod(lambda: planets))
    return StoredGame(
        storage=storage, stack=build_service_stack(storage), turns=turns, planets=planets
    )


def turn_of_write_call(args: tuple) -> int:
    """The turn of a ``(write: TurnWrite)`` call."""
    return args[0].turn_number


def turn_of_ids_call(args: tuple) -> int:
    """The turn of a ``(game_id, perspective, turn_number)`` call."""
    return args[2]


def record_calls(
    monkeypatch,
    owner: type,
    method: str,
    turn_of: Callable[[tuple], int],
    events: list[tuple[str, int]],
) -> None:
    """Record each call of ``owner.method`` by the turn ``turn_of`` reads, then run it."""
    real = getattr(owner, method)

    def recorded(self, *args):
        events.append((f"{owner.__name__}.{method}", turn_of(args)))
        return real(self, *args)

    monkeypatch.setattr(owner, method, recorded)
