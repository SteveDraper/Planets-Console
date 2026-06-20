"""Types for cross-analytic export queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

UnavailableReason = Literal[
    "turn_not_stored",
    "invalid_scope",
    "empty_catalog",
    "ensure_blocked",
    "ensure_cycle",
    "unknown_analytic",
]

PathResultKind = Literal["value", "none", "invalid_path"]

EnsureStepStatus = Literal[
    "not_persisted",
    "persisted",
    "in_progress",
    "baseline",
]


@dataclass(frozen=True)
class ExportScope:
    """Fully resolved export scope for one analytic at one turn.

    Scope identity is ``game_id``, ``perspective``, ``turn``, and optional
    ``player_id`` only. Connection fields on ``TurnAnalyticsOptions`` (warp
    speed, gravitonic movement, flare mode/depth, illustrative routes) are
    **not** part of ``ExportScope`` in the #108 export-framework skeleton.
    They may affect materialized values (e.g. connections exports) but are
    excluded from memo, cycle-detection, and ensure keys until #110 defines
    connection export cache keying.
    """

    game_id: int
    perspective: int
    turn: int
    player_id: int | None = None


@dataclass(frozen=True)
class ExportScopeOverrides:
    """Partial scope parameters supplied on probe/query."""

    turn: int | None = None
    player_id: int | None = None


@dataclass(frozen=True)
class PathPrefixScopeRule:
    """Scope validation keyed by JSONPath prefix."""

    prefix: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnsureDependency:
    """Provider-declared upstream ensure edge."""

    analytic_id: str
    turn_delta: int = 0
    player_id: Literal["same"] | None = "same"


@dataclass(frozen=True)
class EnsureMissingStep:
    """One step reported by probe as not yet terminal."""

    analytic_id: str
    turn: int
    player_id: int | None
    status: EnsureStepStatus


@dataclass(frozen=True)
class ExportProbeResult:
    """Dry-run ensure dependency walk."""

    status: Literal["ok", "unavailable"]
    missing_steps: tuple[EnsureMissingStep, ...] = ()
    total_missing: int = 0
    blocked_inline: bool = False
    reason: UnavailableReason | None = None


@dataclass(frozen=True)
class PathResult:
    """Discriminated outcome for one JSONPath selector."""

    kind: PathResultKind
    value: Any | None = None


@dataclass(frozen=True)
class ExportQueryResult:
    """Top-level export query envelope."""

    status: Literal["ok", "unavailable"]
    paths: dict[str, PathResult] = field(default_factory=dict)
    reason: UnavailableReason | None = None


@dataclass(frozen=True)
class ResolutionKey:
    """Memoization and cycle-detection key.

    ``scope`` carries ``ExportScope`` only; see ``ExportScope`` for the
    intentional exclusion of ``TurnAnalyticsOptions`` connection fields.
    """

    analytic_id: str
    scope: ExportScope
    paths: tuple[str, ...]
