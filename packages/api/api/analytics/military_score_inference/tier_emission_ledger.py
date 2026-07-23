"""Compact per-tier emission ledger for scores inference diagnostics.

Live ``policy_step_attempts`` may include fat constraint snapshots. Durable storage
and first-class wire ``tierEmissions`` keep only the compact ledger fields needed
to answer which solutions each policy step newly admitted (with objectives).
"""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.military_score_inference.models import InferenceSolution

_COMPACT_TIER_EMISSION_KEYS = (
    "policyStepId",
    "policyStepIndex",
    "durationMs",
    "comboCount",
    "seedCount",
    "heldCountBefore",
    "heldCountAfter",
    "newlyAdmittedCount",
    "newlyAdmitted",
    "ladderEarlyStopReason",
    "timeLimited",
    "lastStatus",
    "skipped",
    "tierAllowanceSeconds",
    "reservedForLaterSeconds",
    "spendableSeconds",
)


def compact_solution_emission(solution: InferenceSolution) -> dict[str, object]:
    """Serialize one admitted solution for a tier emission ledger entry."""
    return {
        "objectiveValue": solution.objective_value,
        "actions": [
            {
                "actionId": action.action_id,
                "label": action.label,
                "count": action.count,
            }
            for action in solution.actions
        ],
        "shipBuilds": [
            {
                "comboId": ship_build.combo_id,
                "label": ship_build.label,
                "count": ship_build.count,
            }
            for ship_build in solution.ship_builds
        ],
    }


def tier_emission_fields(
    *,
    duration_ms: float,
    held_count_before: int,
    held_count_after: int,
    newly_admitted: Sequence[InferenceSolution],
    time_limited: bool,
    last_status: str,
    skipped: bool = False,
    ladder_early_stop_reason: str | None = None,
    tier_allowance_seconds: float | None = None,
    reserved_for_later_seconds: float | None = None,
    spendable_seconds: float | None = None,
) -> dict[str, object]:
    """Build emission fields merged into one ``policy_step_attempts`` entry."""
    ranked = sorted(
        newly_admitted,
        key=lambda solution: solution.objective_value,
        reverse=True,
    )
    fields: dict[str, object] = {
        "durationMs": round(duration_ms, 3),
        "heldCountBefore": held_count_before,
        "heldCountAfter": held_count_after,
        "newlyAdmittedCount": len(ranked),
        "newlyAdmitted": [compact_solution_emission(solution) for solution in ranked],
        "timeLimited": time_limited,
        "lastStatus": last_status,
        "skipped": skipped,
    }
    if ladder_early_stop_reason is not None:
        fields["ladderEarlyStopReason"] = ladder_early_stop_reason
    if tier_allowance_seconds is not None:
        fields["tierAllowanceSeconds"] = round(tier_allowance_seconds, 3)
    if reserved_for_later_seconds is not None:
        fields["reservedForLaterSeconds"] = round(reserved_for_later_seconds, 3)
    if spendable_seconds is not None:
        fields["spendableSeconds"] = round(spendable_seconds, 3)
    return fields


def compact_tier_emission_entry(step_diagnostics: dict[str, object]) -> dict[str, object]:
    """Project one step-diagnostics dict to durable/first-class tier emission shape."""
    entry: dict[str, object] = {}
    for key in _COMPACT_TIER_EMISSION_KEYS:
        if key not in step_diagnostics:
            continue
        value = step_diagnostics[key]
        if key == "newlyAdmitted" and isinstance(value, list):
            entry[key] = [_compact_admitted_solution_dict(item) for item in value]
        else:
            entry[key] = value
    return entry


def compact_tier_emissions_from_step_diagnostics(
    step_diagnostics: Sequence[object],
) -> list[dict[str, object]]:
    """Build a durable tier-emissions ledger from live policy step diagnostics."""
    emissions: list[dict[str, object]] = []
    for raw in step_diagnostics:
        if not isinstance(raw, dict):
            continue
        entry = compact_tier_emission_entry(raw)
        if entry.get("policyStepId") is None:
            continue
        emissions.append(entry)
    return emissions


def tier_emissions_from_wire_complete(
    wire_event: dict[str, object],
) -> list[dict[str, object]] | None:
    """Extract compact tier emissions from a wire ``complete`` event."""
    raw = wire_event.get("tierEmissions")
    if isinstance(raw, list) and raw:
        return compact_tier_emissions_from_step_diagnostics(raw)

    diagnostics = wire_event.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    attempts = diagnostics.get("policy_step_attempts")
    if not isinstance(attempts, list) or not attempts:
        return None
    emissions = compact_tier_emissions_from_step_diagnostics(attempts)
    return emissions or None


def _compact_admitted_solution_dict(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    actions_raw = raw.get("actions")
    builds_raw = raw.get("shipBuilds")
    return {
        "objectiveValue": int(raw.get("objectiveValue", 0)),
        "actions": [
            {
                "actionId": str(action.get("actionId", "")),
                "label": str(action.get("label", "")),
                "count": int(action.get("count", 0)),
            }
            for action in actions_raw
            if isinstance(action, dict)
        ]
        if isinstance(actions_raw, list)
        else [],
        "shipBuilds": [
            {
                "comboId": str(build.get("comboId", "")),
                "label": str(build.get("label", "")),
                "count": int(build.get("count", 0)),
            }
            for build in builds_raw
            if isinstance(build, dict)
        ]
        if isinstance(builds_raw, list)
        else [],
    }
