"""Domain types for the fleet turn analytic ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FleetShipDisposition = Literal["active", "lost", "traded", "unknown"]

FleetBoundedOperator = Literal["lte", "gte", "lt", "gt", "eq"]

FleetEvidenceEventKind = Literal[
    "scoreboard_delta",
    "inference_update",
    "sighting",
    "position_update",
    "id_bound_tightened",
    "option_set_match",
    "disposition_change",
    "alibi",
    "possibly_lost",
    "reconciliation_correction",
    "report",
]

FLEET_SHIP_DISPOSITIONS = frozenset({"active", "lost", "traded", "unknown"})

FLEET_BOUNDED_OPERATORS = frozenset({"lte", "gte", "lt", "gt", "eq"})

FLEET_EVIDENCE_EVENT_KINDS = frozenset(
    {
        "scoreboard_delta",
        "inference_update",
        "sighting",
        "position_update",
        "id_bound_tightened",
        "option_set_match",
        "disposition_change",
        "alibi",
        "possibly_lost",
        "reconciliation_correction",
        "report",
    }
)


@dataclass(frozen=True)
class FleetFieldKnown:
    value: int | str | float | bool


@dataclass(frozen=True)
class FleetFieldUnknown:
    pass


@dataclass(frozen=True)
class FleetFieldBounded:
    operator: FleetBoundedOperator
    value: int | float


@dataclass(frozen=True)
class FleetFieldOptions:
    values: tuple[int | str, ...]


@dataclass(frozen=True)
class FleetFieldRegionStarbaseCoord:
    x: int
    y: int


@dataclass(frozen=True)
class FleetFieldRegion:
    planet_ids: tuple[int, ...] = ()
    starbase_coords: tuple[FleetFieldRegionStarbaseCoord, ...] = ()
    overlay_id: str | None = None


FleetFieldConstraint = (
    FleetFieldKnown | FleetFieldUnknown | FleetFieldBounded | FleetFieldOptions | FleetFieldRegion
)


@dataclass(frozen=True)
class FleetBuildOptionSet:
    combo_id: str | None = None
    label: str = ""
    solution_rank_weight: int = 0
    hull_id: int | None = None
    engine_id: int | None = None
    beam_id: int | None = None
    torp_id: int | None = None
    beam_count: int = 0
    launcher_count: int = 0


@dataclass(frozen=True)
class FleetLastSeen:
    turn: int
    x: int
    y: int
    planet_id: int | None = None


@dataclass(frozen=True)
class FleetPossiblyLost:
    since_turn: int
    source: str = ""


@dataclass(frozen=True)
class FleetAlibi:
    after_turn: int
    sighting_turn: int
    source: str = ""


@dataclass
class FleetRowQualifiers:
    possibly_lost: FleetPossiblyLost | None = None
    alibi: FleetAlibi | None = None


@dataclass(frozen=True)
class FleetEvidenceEvent:
    event_id: str
    kind: FleetEvidenceEventKind
    turn: int
    source: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass
class FleetShipRecordFields:
    ship_id: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    hull: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    engine: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    beams: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    launchers: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    built_turn: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)
    location: FleetFieldConstraint = field(default_factory=FleetFieldUnknown)


@dataclass
class FleetShipRecord:
    record_id: str
    disposition: FleetShipDisposition = "active"
    qualifiers: FleetRowQualifiers = field(default_factory=FleetRowQualifiers)
    fields: FleetShipRecordFields = field(default_factory=FleetShipRecordFields)
    build_option_sets: list[FleetBuildOptionSet] = field(default_factory=list)
    display_default_option_set_index: int | None = None
    last_seen: FleetLastSeen | None = None
    events: list[FleetEvidenceEvent] = field(default_factory=list)


@dataclass(frozen=True)
class FleetCountDiscrepancy:
    host_turn: int
    active_row_count: int
    scoreboard_implied_count: int
    report_refs: tuple[str, ...] = ()


@dataclass
class FleetAcquisitionLedger:
    player_id: int
    player_name: str = ""
    records: list[FleetShipRecord] = field(default_factory=list)
    discrepancy: FleetCountDiscrepancy | None = None


@dataclass
class FleetTurnSnapshot:
    analytic_id: str = "fleet"
    game_id: int = 0
    perspective: int = 0
    turn: int = 0
    players: list[FleetAcquisitionLedger] = field(default_factory=list)
