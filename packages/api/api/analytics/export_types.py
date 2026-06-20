"""Types for cross-analytic export queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

UnavailableReason = Literal[
    "turn_not_stored",
    "invalid_scope",
    "empty_catalog",
    "ensure_blocked",
    "ensure_cycle",
    "unknown_analytic",
]

PathResultKind = Literal["value", "none", "invalid_path"]

# Probe missing-step lifecycle on the wire. The #108 skeleton walker only
# emits ``not_persisted`` on ``EnsureMissingStep``; ``persisted``,
# ``in_progress``, and ``baseline`` are reserved for scheduler and
# persistence probes in #109+.
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


class ExportScopeOverridesMapping(TypedDict, total=False):
    """Dict-shaped partial scope overrides accepted by export probe/query."""

    turn: int
    player_id: int | None


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
    """One ensure step that probe reports as not yet terminal.

    The #108 skeleton probe walk only appends rows with
    ``status="not_persisted"``. Steps that are already persisted, attached
    to in-flight scheduler work, or at an analytic-specific ensure baseline are
    omitted from ``missing_steps`` entirely rather than listed with another
    status. Other ``EnsureStepStatus`` values are reserved for follow-up probe
    work (#109+) that distinguishes persistence, in-progress, and baseline.
    """

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
