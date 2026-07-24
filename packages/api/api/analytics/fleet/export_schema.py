"""JSON Schema for fleet turn analytic export values."""

from __future__ import annotations

from typing import Any

_FIELD_CONSTRAINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Partial-knowledge constraint on one fleet ship record field: known, unknown, "
        "bounded, options, or region."
    ),
    "additionalProperties": True,
    "properties": {
        "kind": {
            "type": "string",
            "description": "Constraint discriminator: known, unknown, bounded, options, or region.",
        },
    },
}

_BUILD_OPTION_SET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "One consistent fitted ship spec from a held scores inference solution, used while "
        "inferred acquisition rows remain ambiguous."
    ),
    "additionalProperties": True,
    "properties": {
        "comboId": {
            "type": "string",
            "description": "Stable ship build combo id from the inference catalog.",
        },
        "label": {
            "type": "string",
            "description": "Human-readable combo label for display.",
        },
        "solutionRankWeight": {
            "type": "integer",
            "description": "Inference solution rank weight for this option set.",
        },
        "hullId": {
            "type": "integer",
            "description": "Host hull id for this option set.",
        },
        "engineId": {
            "type": "integer",
            "description": "Host engine id for this option set.",
        },
    },
}

_EVIDENCE_EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "One append-only fleet evidence event on a ship record timeline.",
    "additionalProperties": True,
    "properties": {
        "eventId": {
            "type": "string",
            "description": "Stable event id within the record timeline.",
        },
        "kind": {
            "type": "string",
            "description": (
                "Evidence kind, e.g. scoreboard_delta, inference_update, sighting, "
                "option_set_match, count_collapse."
            ),
        },
        "turn": {
            "type": "integer",
            "description": "Host turn the event applies to.",
        },
        "source": {
            "type": "string",
            "description": "Provenance label for the evidence source.",
        },
    },
}

_SHIP_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "One fleet ship record in a player acquisition ledger.",
    "properties": {
        "recordId": {
            "type": "string",
            "description": "Stable record id within the player ledger.",
        },
        "disposition": {
            "type": "string",
            "description": "Fleet ship disposition: active, lost, traded, unknown, or merged.",
        },
        "qualifiers": {
            "type": "object",
            "description": "Row-level qualifiers such as possibly lost or alibi.",
            "additionalProperties": True,
        },
        "fields": {
            "type": "object",
            "description": "Partial-knowledge ship attributes for this record.",
            "additionalProperties": True,
            "properties": {
                "shipId": _FIELD_CONSTRAINT_SCHEMA,
                "hull": _FIELD_CONSTRAINT_SCHEMA,
                "engine": _FIELD_CONSTRAINT_SCHEMA,
                "beams": _FIELD_CONSTRAINT_SCHEMA,
                "launchers": _FIELD_CONSTRAINT_SCHEMA,
                "builtTurn": _FIELD_CONSTRAINT_SCHEMA,
                "location": _FIELD_CONSTRAINT_SCHEMA,
            },
        },
        "buildOptionSets": {
            "type": "array",
            "description": "Held build option sets while the row remains ambiguous.",
            "items": _BUILD_OPTION_SET_SCHEMA,
        },
        "displayDefaultOptionSetIndex": {
            "type": "integer",
            "description": "Index into buildOptionSets chosen for default display.",
        },
        "lastSeen": {
            "type": "object",
            "description": "Most recent sighting position for this record.",
            "additionalProperties": True,
        },
        "events": {
            "type": "array",
            "description": "Append-only evidence timeline for this record.",
            "items": _EVIDENCE_EVENT_SCHEMA,
        },
    },
}

_DISCREPANCY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Player-level fleet count discrepancy when active rows exceed scoreboard-implied count."
    ),
    "properties": {
        "hostTurn": {
            "type": "integer",
            "description": "Host turn where the discrepancy was recorded.",
        },
        "activeRowCount": {
            "type": "integer",
            "description": "Count of active fleet ship records at that turn.",
        },
        "scoreboardImpliedCount": {
            "type": "integer",
            "description": "Ship count implied by scoreboard deltas.",
        },
    },
}

_PLAYER_LEDGER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Fleet acquisition ledger for one player.",
    "properties": {
        "playerId": {
            "type": "integer",
            "description": "Host player id for this ledger.",
        },
        "playerName": {
            "type": "string",
            "description": "Display name for the player.",
        },
        "records": {
            "type": "array",
            "description": "Fleet ship records tracked for this player.",
            "items": _SHIP_RECORD_SCHEMA,
        },
        "discrepancy": _DISCREPANCY_SCHEMA,
    },
}

_COMPOSITION_HISTOGRAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Histogram of host component ids keyed by stringified id. Each value is the count of "
        "active fleet ship records with that known fitted component type."
    ),
    "additionalProperties": {
        "type": "integer",
        "minimum": 0,
        "description": "Number of active fleet ship records with this component id.",
    },
}

_MAX_TECH_LEVEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Maximum host tech level per component axis, derived from known component ids in the "
        "histograms and engine field values. Axes with no catalog-resolvable known components "
        "are omitted."
    ),
    "properties": {
        "hulls": {
            "type": "integer",
            "minimum": 1,
            "description": "Highest techlevel among known hull ids in hullTypes.",
        },
        "engines": {
            "type": "integer",
            "minimum": 1,
            "description": "Highest techlevel among known engine ids on active ship records.",
        },
        "launchers": {
            "type": "integer",
            "minimum": 1,
            "description": "Highest techlevel among known torpedo ids in launcherTypes.",
        },
        "beams": {
            "type": "integer",
            "minimum": 1,
            "description": "Highest techlevel among known beam ids in beamTypes.",
        },
    },
}

_COMPOSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Per-player aggregated fleet composition derived from the acquisition ledger. "
        "Belief-set histograms count active rows using known fitted component fields "
        "and the union of fleet build option sets on inferred rows."
    ),
    "properties": {
        "hullTypes": {
            **_COMPOSITION_HISTOGRAM_SCHEMA,
            "description": (
                "Belief-set hull histogram on active ships. Keys are host hull ids as "
                "strings; values are ship counts. Includes known hull constraints and "
                "hull ids from fleet build option sets; bounded, options, and region-only "
                "constraints contribute no ids until resolved."
            ),
        },
        "engineTypes": {
            **_COMPOSITION_HISTOGRAM_SCHEMA,
            "description": (
                "Belief-set engine histogram on active ships. Keys are host engine ids as "
                "strings; values are ship counts. Includes known engine constraints and "
                "engine ids from fleet build option sets."
            ),
        },
        "beamTypes": {
            **_COMPOSITION_HISTOGRAM_SCHEMA,
            "description": (
                "Belief-set beam histogram on active ships. Keys are host beam ids as "
                "strings; values are ship counts. Includes known positive beam constraints "
                "and beam ids from fleet build option sets. Known zero (no beams) is "
                "excluded."
            ),
        },
        "launcherTypes": {
            **_COMPOSITION_HISTOGRAM_SCHEMA,
            "description": (
                "Belief-set launcher/torp histogram on active ships. Keys are host torpedo "
                "ids as strings; values are ship counts. Includes known positive launcher "
                "constraints and torp ids from fleet build option sets. Feeds scores "
                "inference fleet torp overlay (#87). Known zero (no tubes) is excluded."
            ),
        },
        "torpedoTypesLoaded": {
            **_COMPOSITION_HISTOGRAM_SCHEMA,
            "description": (
                "Histogram of known torpedo types currently loaded on active ships when the "
                "ledger has observation evidence for loaded ammo. Empty when loaded-torp "
                "evidence is not persisted on ship records."
            ),
        },
        "maxTechLevel": _MAX_TECH_LEVEL_SCHEMA,
    },
}

_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Export materialization lifecycle for this scoped fleet query. searchStatus reflects "
        "scores inference status for the same player and host turn."
    ),
    "properties": {
        "searchStatus": {
            "type": "string",
            "enum": [
                "not_started",
                "in_progress",
                "paused",
                "stopped",
                "complete",
            ],
            "description": (
                "Scores inference search lifecycle for this player scope on the host turn. "
                "Consumers should warn when not complete even if placeholder fleet rows exist."
            ),
        },
        "solutionsHeld": {
            "type": "integer",
            "description": (
                "Count of held scores inference solutions for this player scope. Omitted when zero."
            ),
        },
        "hostTurn": {
            "type": "integer",
            "description": "Turn number for the materialized export scope.",
        },
    },
}

EXPORT_VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Fleet turn analytic export tree for one query scope. Mirrors the fleet acquisition "
        "ledger with per-player records and discrepancies. meta.searchStatus carries scores "
        "materialization lifecycle for the scoped player."
    ),
    "properties": {
        "meta": _META_SCHEMA,
        "composition": _COMPOSITION_SCHEMA,
        "players": {
            "type": "array",
            "description": (
                "Per-player fleet acquisition ledgers. When player_id is set on the query "
                "scope, contains only that player's ledger."
            ),
            "items": _PLAYER_LEDGER_SCHEMA,
        },
    },
}
