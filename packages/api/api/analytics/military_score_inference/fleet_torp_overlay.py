"""Fleet-informed torpedo admission and ranking overlay for scores inference (#87).

Glossary: CONTEXT.md (**Inference fleet launcher belief set**, **Inference aggregate
admission**, **Inference torp escape tier**, **Inference torp misalignment penalty**).

Absent ``FleetTorpOverlay`` input behaves like an **empty belief set** (no early torp
admission; strong down-weight at escape tier). Use ``FleetTorpOverlay.disabled()`` to
skip overlay logic and retain the pre-#87 catalog (population priors only).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from api.analytics.fleet.belief_set_components import launcher_component_ids_from_records
from api.analytics.fleet.types import FleetShipRecord
from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
    is_torp_load_action_id,
)
from api.analytics.military_score_inference.models import ProbabilityBucket
from api.analytics.military_score_inference.tier_policy import (
    TORP_ESCAPE_TIER_STEP_ID,
    FleetInferenceTuning,
    InferenceTierPolicyStep,
    torp_escape_tier_index,
)

__all__ = [
    "FleetLauncherBeliefSet",
    "FleetTorpOverlay",
    "FleetTorpOverlayDiagnostics",
    "admitted_torp_ids_for_policy_step",
    "apply_torp_misalignment_penalty_to_buckets",
    "effective_fleet_torp_overlay",
    "launcher_belief_set_from_composition",
    "launcher_belief_set_from_fleet_records",
    "apply_torp_misalignment_penalties_to_catalog",
    "build_fleet_torp_overlay_diagnostics",
    "torp_load_action_id",
]


@dataclass(frozen=True)
class FleetLauncherBeliefSet:
    """Torp ids fitted on ships the player is believed to own at prior turn."""

    torp_ids: frozenset[int]

    @property
    def is_empty(self) -> bool:
        return not self.torp_ids


@dataclass(frozen=True)
class FleetTorpOverlay:
    """Optional per-solve fleet torp overlay input."""

    belief_set: FleetLauncherBeliefSet
    enabled: bool = True

    @staticmethod
    def disabled() -> FleetTorpOverlay:
        """Skip #87 admission filtering and misalignment penalties (#86 baseline)."""
        return FleetTorpOverlay(
            belief_set=FleetLauncherBeliefSet(frozenset()),
            enabled=False,
        )

    @staticmethod
    def from_torp_ids(torp_ids: frozenset[int] | Iterable[int]) -> FleetTorpOverlay:
        return FleetTorpOverlay(belief_set=FleetLauncherBeliefSet(frozenset(torp_ids)))


@dataclass(frozen=True)
class FleetTorpOverlayDiagnostics:
    applied: bool
    enabled: bool
    belief_set_torp_ids: tuple[int, ...]
    admitted_torp_ids: tuple[int, ...]
    policy_step_id: str
    escape_tier_used: bool
    torp_misalignment_log_penalty: int

    def to_payload(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "enabled": self.enabled,
            "beliefSetTorpIds": list(self.belief_set_torp_ids),
            "admittedTorpIds": list(self.admitted_torp_ids),
            "policyStepId": self.policy_step_id,
            "escapeTierUsed": self.escape_tier_used,
            "torpMisalignmentLogPenalty": self.torp_misalignment_log_penalty,
        }


def effective_fleet_torp_overlay(overlay: FleetTorpOverlay | None) -> FleetTorpOverlay:
    if overlay is None:
        return FleetTorpOverlay(belief_set=FleetLauncherBeliefSet(frozenset()), enabled=True)
    return overlay


def launcher_belief_set_from_fleet_records(
    records: Iterable[FleetShipRecord],
) -> FleetLauncherBeliefSet:
    """Union launcher/torp ids from known fields and all fleet build option sets."""
    return FleetLauncherBeliefSet(launcher_component_ids_from_records(records))


def launcher_belief_set_from_composition(composition: dict[str, object]) -> FleetLauncherBeliefSet:
    """Derive belief set from fleet ``$.composition.launcherTypes`` export branch."""
    launcher_types = composition.get("launcherTypes", {})
    if not isinstance(launcher_types, dict):
        return FleetLauncherBeliefSet(frozenset())
    torp_ids: set[int] = set()
    for key in launcher_types:
        if isinstance(key, str) and key.isdecimal():
            torp_id = int(key)
            if torp_id > 0:
                torp_ids.add(torp_id)
    return FleetLauncherBeliefSet(frozenset(torp_ids))


def torp_load_action_id(torp_id: int) -> str:
    return f"{SHIP_TORPS_LOADED_ACTION_PREFIX}{torp_id}"


def admitted_torp_ids_for_policy_step(
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    policy_steps: tuple[InferenceTierPolicyStep, ...],
    eligible_torp_ids: frozenset[int],
    overlay: FleetTorpOverlay,
) -> frozenset[int]:
    if SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY not in policy_step.aggregate_allowlist:
        return frozenset()

    if not overlay.enabled:
        return eligible_torp_ids

    if policy_step.alpha == 0:
        return eligible_torp_ids

    escape_index = torp_escape_tier_index(policy_steps)
    if escape_index is not None and policy_step_index < escape_index:
        if overlay.belief_set.is_empty:
            return frozenset()
        return overlay.belief_set.torp_ids & eligible_torp_ids

    if policy_step.id == TORP_ESCAPE_TIER_STEP_ID or (
        escape_index is not None and policy_step_index > escape_index
    ):
        return eligible_torp_ids

    return frozenset()


def apply_torp_misalignment_penalty_to_buckets(
    buckets: tuple[ProbabilityBucket, ...],
    *,
    penalty: int,
) -> tuple[ProbabilityBucket, ...]:
    if penalty <= 0:
        return buckets
    adjusted: list[ProbabilityBucket] = []
    for bucket in buckets:
        if bucket.lower_count == 0 and bucket.upper_count == 0:
            adjusted.append(bucket)
            continue
        adjusted.append(
            replace(
                bucket,
                marginal_weight=max(0, bucket.marginal_weight - penalty),
            )
        )
    return tuple(adjusted)


def apply_torp_misalignment_penalties_to_catalog(
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    overlay: FleetTorpOverlay,
    tuning: FleetInferenceTuning,
) -> dict[str, tuple[ProbabilityBucket, ...]]:
    if not overlay.enabled or tuning.torp_misalignment_log_penalty <= 0:
        return probability_buckets

    belief_ids = overlay.belief_set.torp_ids
    penalty = tuning.torp_misalignment_log_penalty
    adjusted = dict(probability_buckets)
    for action_id in list(adjusted.keys()):
        if not is_torp_load_action_id(action_id):
            continue
        torp_id = int(action_id.removeprefix(SHIP_TORPS_LOADED_ACTION_PREFIX))
        if torp_id in belief_ids:
            continue
        adjusted[action_id] = apply_torp_misalignment_penalty_to_buckets(
            adjusted[action_id],
            penalty=penalty,
        )
    return adjusted


def build_fleet_torp_overlay_diagnostics(
    *,
    overlay: FleetTorpOverlay,
    tuning: FleetInferenceTuning,
    policy_step: InferenceTierPolicyStep,
    admitted_torp_ids: frozenset[int],
) -> FleetTorpOverlayDiagnostics:
    return FleetTorpOverlayDiagnostics(
        applied=overlay.enabled,
        enabled=overlay.enabled,
        belief_set_torp_ids=tuple(sorted(overlay.belief_set.torp_ids)),
        admitted_torp_ids=tuple(sorted(admitted_torp_ids)),
        policy_step_id=policy_step.id,
        escape_tier_used=policy_step.id == TORP_ESCAPE_TIER_STEP_ID,
        torp_misalignment_log_penalty=tuning.torp_misalignment_log_penalty,
    )
