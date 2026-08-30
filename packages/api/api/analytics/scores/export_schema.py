"""JSON Schema for scores turn analytic export values."""

from __future__ import annotations

from typing import Any

_ACTION_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "One aggregate build action attributed to this solution.",
    "properties": {
        "actionId": {
            "type": "string",
            "description": "Stable catalog action id (e.g. planet_defense_posts_added_total).",
        },
        "label": {
            "type": "string",
            "description": "Human-readable action label for display.",
        },
        "count": {
            "type": "integer",
            "description": "How many units of this aggregate action the solution assigns.",
        },
    },
}

_SHIP_BUILD_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "One ship build combo attributed to this solution.",
    "properties": {
        "comboId": {
            "type": "string",
            "description": "Stable ship build combo id from the inference catalog.",
        },
        "label": {
            "type": "string",
            "description": "Human-readable combo label for display.",
        },
        "count": {
            "type": "integer",
            "description": "How many ships of this combo the solution builds.",
        },
        "hullId": {
            "type": "integer",
            "description": "Host hull id for this combo.",
        },
        "engineId": {
            "type": "integer",
            "description": "Host engine id for this combo.",
        },
        "beamId": {
            "type": ["integer", "null"],
            "description": (
                "Host beam weapon id when beamCount > 0; JSON null when no beam is "
                "fitted (beamCount == 0). Absence of a beam is not encoded as a "
                "numeric sentinel."
            ),
        },
        "torpId": {
            "type": ["integer", "null"],
            "description": (
                "Host torpedo id when launcherCount > 0; JSON null when no torpedo "
                "launcher is fitted (launcherCount == 0). Absence of a torpedo is "
                "not encoded as a numeric sentinel."
            ),
        },
        "beamCount": {
            "type": "integer",
            "description": "Number of beam slots filled on this hull.",
        },
        "launcherCount": {
            "type": "integer",
            "description": "Number of torpedo launcher slots filled on this hull.",
        },
    },
}

_ARITHMETIC_LINE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Military score contribution from one aggregate action or ship build combo "
        "in this solution."
    ),
    "properties": {
        "actionId": {
            "type": "string",
            "description": "Present when the line item is an aggregate action.",
        },
        "comboId": {
            "type": "string",
            "description": "Present when the line item is a ship build combo.",
        },
        "label": {
            "type": "string",
            "description": "Human-readable label for the contributing action or combo.",
        },
        "count": {
            "type": "integer",
            "description": "Units of the action or combo included in this solution.",
        },
        "counterpartyPlayerId": {
            "type": "integer",
            "description": (
                "Other scoreboard-row owner when public pairing pins one counterparty "
                "(gift, trade, or acquired ship)."
            ),
        },
        "scoreDelta2xPerUnit": {
            "type": "integer",
            "description": "Host military score delta (times two) contributed per unit.",
        },
        "militaryChangePerUnit": {
            "type": "integer",
            "description": "Displayed military score change per unit (scoreDelta2xPerUnit // 2).",
        },
        "scoreDelta2xSubtotal": {
            "type": "integer",
            "description": "Total scoreDelta2xPerUnit * count for this line item.",
        },
        "militaryChangeSubtotal": {
            "type": "integer",
            "description": "Total military score change for this line item (subtotal // 2).",
        },
    },
}

_MILITARY_SCORE_ARITHMETIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Reconciliation of how this solution's actions and ship builds sum to the "
        "observed military score delta for the row."
    ),
    "properties": {
        "observedMilitaryChange": {
            "type": "integer",
            "description": "Observed military score change for the row (display units).",
        },
        "observedMilitaryDelta2x": {
            "type": "integer",
            "description": "Observed military score delta in host times-two units.",
        },
        "explainedMilitaryChange": {
            "type": "integer",
            "description": "Military score change explained by this solution (display units).",
        },
        "explainedMilitaryDelta2x": {
            "type": "integer",
            "description": "Explained military score delta in host times-two units.",
        },
        "militaryPartitionSlack2x": {
            "type": "integer",
            "description": "Allowed slack (times-two units) when matching observed vs explained.",
        },
        "matchesObserved": {
            "type": "boolean",
            "description": (
                "True when explainedMilitaryDelta2x is within militaryPartitionSlack2x "
                "of observedMilitaryDelta2x."
            ),
        },
        "lineItems": {
            "type": "array",
            "description": "Per-action and per-combo military score contributions.",
            "items": _ARITHMETIC_LINE_ITEM_SCHEMA,
        },
    },
}

_SOLUTION_WIRE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "One held build explanation: aggregate actions, ship builds, rank weight, and "
        "optional military score reconciliation."
    ),
    "properties": {
        "objectiveValue": {
            "type": "integer",
            "description": (
                "Inference solution rank weight (UI: Plausibility). Higher means more "
                "plausible. Built from scaled integer sums of prior log-probability "
                "terms (bucketed aggregate bins, ship-combo weights) plus ranking "
                "heuristics (occurrence cost, tier overflow, partial weapon-slot "
                "penalties). Interpret as plausibility on a pseudo log-likelihood "
                "scale: monotonic with prior support, not a calibrated probability "
                "or literal joint log-likelihood. Wire name kept for solver history."
            ),
        },
        "actions": {
            "type": "array",
            "description": "Aggregate build actions assigned by this explanation.",
            "items": _ACTION_ITEM_SCHEMA,
        },
        "shipBuilds": {
            "type": "array",
            "description": "Ship build combos assigned by this explanation.",
            "items": _SHIP_BUILD_ITEM_SCHEMA,
        },
        "militaryScoreArithmetic": _MILITARY_SCORE_ARITHMETIC_SCHEMA,
    },
}

_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Export materialization lifecycle for this scoped scores query.",
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
                "Inference search lifecycle for this row scope: not_started (no work "
                "yet), in_progress (scheduler or stream active), paused (global "
                "pause on active stream), stopped (user halt with held solutions), "
                "complete (terminal persisted or immediate result). Product inference "
                "outcomes (skip, residual, no_exact_solution) are not encoded here; "
                "they live on $.status."
            ),
        },
        "solutionsHeld": {
            "type": "integer",
            "description": (
                "Count of solutions currently held in the top-K ladder. Omitted when zero."
            ),
        },
        "hostTurn": {
            "type": "integer",
            "description": "Turn number for the materialized export scope.",
        },
    },
}

_DIAGNOSTICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Developer-facing inference diagnostics for this row. Same shape as scores row "
        "inference diagnostics wire. Present when persisted, admission, or scheduler "
        "inference produced diagnostics. Additional solver-owned keys may appear "
        "beyond those listed."
    ),
    "additionalProperties": True,
    "properties": {
        "turn": {
            "type": "integer",
            "description": "Turn number the diagnostics were produced for.",
        },
        "constraints": {
            "type": "object",
            "description": (
                "Observed constraint deltas and hard-limit display payload for the "
                "inference problem."
            ),
            "additionalProperties": True,
        },
        "actionCatalog": {
            "type": "object",
            "description": "Snapshot of aggregate actions and ship combos considered.",
            "additionalProperties": True,
        },
        "rankingHeuristics": {
            "type": "object",
            "description": "Ranking heuristic configuration applied during search.",
            "additionalProperties": True,
        },
        "solver": {
            "type": "object",
            "description": "Raw solver status and statistics from the inference run.",
            "additionalProperties": True,
        },
        "catalog_size": {
            "type": "integer",
            "description": "Total aggregate actions plus ship build combos in the catalog.",
        },
        "aggregate_action_count": {
            "type": "integer",
            "description": "Number of aggregate actions in the inference catalog.",
        },
        "ship_build_combo_count": {
            "type": "integer",
            "description": "Number of ship build combos in the inference catalog.",
        },
        "policy_step_id": {
            "type": "string",
            "description": "Active catalog policy step id for this inference run.",
        },
        "policy_step_index": {
            "type": "integer",
            "description": "Zero-based index of the active catalog policy step.",
        },
        "bucketed_action_count": {
            "type": "integer",
            "description": "Aggregate actions that use bucketed magnitude priors.",
        },
        "priorWeights": {
            "type": "object",
            "description": "Prior weight diagnostics for the active catalog step.",
            "additionalProperties": True,
        },
        "policy_steps_attempted": {
            "type": "array",
            "description": "Policy step ids attempted during multi-step inference.",
            "items": {
                "type": "string",
                "description": "One attempted policy step id.",
            },
        },
        "policy_step_attempts": {
            "type": "array",
            "description": (
                "Per-step attempt diagnostics from multi-step inference, including "
                "durationMs and newlyAdmitted solution emissions (objective + compact "
                "build/action signature)."
            ),
            "items": {
                "type": "object",
                "description": "Diagnostics for one policy step attempt.",
                "additionalProperties": True,
            },
        },
        "reason": {
            "type": "string",
            "description": "Terminal reason when inference did not run or failed early.",
        },
    },
}

_HULL_CATALOG_MASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Effective hull catalog mask for this player scope. Present when player_id is "
        "set on the query scope."
    ),
    "properties": {
        "enabledHullIds": {
            "type": "array",
            "description": "Sorted hull ids enabled for ship build inference.",
            "items": {
                "type": "integer",
                "description": "One enabled host hull id.",
            },
        },
    },
}

_PLACEHOLDER_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "One post-unsat placeholder: unknown military ship (hull sentinel -1, typed id "
        "unknown_military_ship) or observation-derived generic freighter (hull id 0, "
        "typed id combo_freighter). Not a ranked solutions[] entry. Residual / "
        "no_exact_solution rows include the collection; skip rows keep an empty array."
    ),
    "additionalProperties": True,
    "properties": {
        "id": {
            "type": "string",
            "description": "Typed placeholder id: unknown_military_ship or combo_freighter.",
        },
        "hullId": {
            "type": "integer",
            "description": (
                "Hull sentinel: -1 for unknown military ship, 0 for generic freighter."
            ),
        },
        "count": {
            "type": "integer",
            "description": "Unexplained positive remainder count for this placeholder.",
        },
        "militaryScoreDelta2xMin": {
            "type": "integer",
            "description": (
                "Per-unit military score delta (times two) lower bound from the race "
                "construction envelope. Present on unknown military ship placeholders."
            ),
        },
        "militaryScoreDelta2xMax": {
            "type": "integer",
            "description": (
                "Per-unit military score delta (times two) upper bound from the race "
                "construction envelope. Present on unknown military ship placeholders."
            ),
        },
        "buildSlotUsage": {
            "type": "integer",
            "description": "Starbase build-slot usage per unit (1 for both placeholder kinds).",
        },
    },
}

_PRODUCT_STATUS_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": [
        "exact",
        "moderate_residual",
        "mine_score_residual",
        "no_exact_solution",
        "viewpoint_owner",
        "dead",
        "full_alliance",
        "horwasp",
        "no_prior_turn",
        "player_not_found",
        "invalid_problem",
        "solver_error",
        "time_limited",
        "stopped",
        "paused",
        "pending",
        "fetch_error",
    ],
    "description": (
        "Product inference outcome for this row. Distinct from $.meta.searchStatus "
        "(lifecycle only). Includes exact, both residual statuses, no_exact_solution, "
        "per-reason admission skips, and remaining solver/problem terminals. Stealth "
        "Mode is build-inference availability, not a row status."
    ),
}

EXPORT_VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Scores turn analytic export tree for one query scope. Mirrors held inference "
        "row wire shape: lifecycle in meta, product status / leftover / placeholders "
        "as siblings of ranked solutions, optional diagnostics, and optional hull "
        "catalog mask when player_id is set."
    ),
    "properties": {
        "meta": _META_SCHEMA,
        "status": _PRODUCT_STATUS_SCHEMA,
        "solutions": {
            "type": "array",
            "description": (
                "Held top-K build explanations for this row scope, highest "
                "objectiveValue first. $.solutions[0] is the top explanation."
            ),
            "items": _SOLUTION_WIRE_SCHEMA,
        },
        "placeholders": {
            "type": "array",
            "description": (
                "Post-unsat placeholder collection for residual / no_exact_solution / "
                "skip rows. Sibling of $.solutions. Residual leftover stays on "
                "unexplainedMilitaryDelta2x, not assigned onto these ships. Skip rows "
                "keep an empty array."
            ),
            "items": _PLACEHOLDER_ITEM_SCHEMA,
        },
        "unexplainedMilitaryDelta2x": {
            "type": "integer",
            "description": (
                "Unexplained military score leftover in host times-two units for "
                "moderate_residual, mine_score_residual, and no_exact_solution rows. "
                "Omitted for exact and admission-skip terminals. Sibling of "
                "$.solutions; not assigned onto placeholders."
            ),
        },
        "diagnostics": _DIAGNOSTICS_SCHEMA,
        "tierEmissions": {
            "type": "array",
            "description": (
                "Compact per-policy-step emission ledger (step id, wall ms, newly "
                "admitted solutions with objective values). Durable first-class "
                "field; not stripped with full solver diagnostics."
            ),
            "items": {
                "type": "object",
                "description": "One policy-step emission record.",
                "additionalProperties": True,
            },
        },
        "hullCatalogMask": _HULL_CATALOG_MASK_SCHEMA,
    },
}
