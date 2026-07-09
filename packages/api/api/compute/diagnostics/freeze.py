"""Freeze-armed state and per-shell player allowlists for compute diagnostics."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShellContextKey:
    """Identity for one shell diagnostic context."""

    game_id: int
    perspective: int
    turn: int


@dataclass
class FreezeGameState:
    """Per-game freeze armed flag (sticky across turn/perspective within the game)."""

    freeze_armed: bool = False


@dataclass
class FreezeShellState:
    """Per-shell player allowlist; resets on each context change."""

    allowlisted_player_ids: set[int] = field(default_factory=set)


class ComputeDiagnosticsFreezeState:
    """Process-wide freeze and allowlist registry for compute diagnostics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._game_state: dict[int, FreezeGameState] = {}
        self._shell_state: dict[ShellContextKey, FreezeShellState] = {}

    def freeze_armed_for_game(self, game_id: int) -> bool:
        with self._lock:
            return self._game_state.get(game_id, FreezeGameState()).freeze_armed

    def set_freeze_armed(self, game_id: int, *, freeze_armed: bool) -> None:
        with self._lock:
            state = self._game_state.setdefault(game_id, FreezeGameState())
            state.freeze_armed = freeze_armed
            if not freeze_armed:
                self._shell_state = {
                    key: value for key, value in self._shell_state.items() if key.game_id != game_id
                }

    def on_shell_context_entered(self, shell: ShellContextKey) -> None:
        """Reset allowlist when the operator changes shell context."""
        with self._lock:
            self._shell_state[shell] = FreezeShellState()

    def allowlisted_player_ids(self, shell: ShellContextKey) -> frozenset[int]:
        with self._lock:
            shell_state = self._shell_state.get(shell)
            if shell_state is None:
                return frozenset()
            return frozenset(shell_state.allowlisted_player_ids)

    def set_allowlisted_player_ids(
        self,
        shell: ShellContextKey,
        player_ids: frozenset[int],
    ) -> None:
        with self._lock:
            shell_state = self._shell_state.setdefault(shell, FreezeShellState())
            shell_state.allowlisted_player_ids = set(player_ids)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._game_state.clear()
            self._shell_state.clear()
