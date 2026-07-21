"""Fleet-informed torpedo admission and ranking overlay for scores inference (#87).

Glossary: CONTEXT.md (**Inference fleet launcher belief set**, **Inference aggregate
admission**, **Inference torp escape tier**, **Inference torp misalignment penalty**,
**Inference fleet launcher belief mass**).

Absent ``FleetTorpOverlay`` input behaves like an **empty belief set** (no early torp
admission; strong down-weight at escape tier). Use ``FleetTorpOverlay.disabled()`` to
skip overlay logic and retain the pre-#87 catalog (population priors only).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from api.analytics.fleet.belief_set_components import launcher_component_ids_from_records
from api.analytics.fleet.option_set_mass import launcher_belief_mass_by_torp_id_from_records
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
    "effective_torp_misalignment_log_penalty",
    "launcher_belief_set_from_composition",
    "launcher_belief_set_from_fleet_records",
    "apply_torp_misalignment_penalties_to_catalog",
    "build_fleet_torp_overlay_diagnostics",
    "overlay_from_fleet_records",
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
    """Optional per-solve fleet torp overlay input.

    Misalignment ranking uses belief mass, not set membership alone. Invariant:
    when ``enabled`` and ``belief_set`` is non-empty, an **empty**
    ``launcher_belief_mass_by_torp_id`` means membership-only evidence and is
    seeded to hard mass 1.0 for every belief-set id. A **non-empty** mass map
    is authoritative (missing keys stay mass 0 -- soft-mass overlays where
    admission union may exceed high-mass ids).
    """

    belief_set: FleetLauncherBeliefSet
    enabled: bool = True
    # Player-level launcher belief mass per torp id (hard or soft). Empty map
    # with a non-empty enabled belief set is seeded to 1.0 per id in
    # ``__post_init__``. Non-empty maps are left as provided; missing ids are
    # mass 0. ``from_torp_ids`` also seeds mass 1 explicitly (synthetic hard).
    launcher_belief_mass_by_torp_id: Mapping[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.enabled
            and not self.belief_set.is_empty
            and not self.launcher_belief_mass_by_torp_id
        ):
            object.__setattr__(
                self,
                "launcher_belief_mass_by_torp_id",
                dict.fromkeys(self.belief_set.torp_ids, 1.0),
            )

    @staticmethod
    def disabled() -> FleetTorpOverlay:
        """Skip #87 admission filtering and misalignment penalties (#86 baseline)."""
        return FleetTorpOverlay(
            belief_set=FleetLauncherBeliefSet(frozenset()),
            enabled=False,
        )

    @staticmethod
    def from_torp_ids(torp_ids: frozenset[int] | Iterable[int]) -> FleetTorpOverlay:
        ids = frozenset(torp_ids)
        return FleetTorpOverlay(
            belief_set=FleetLauncherBeliefSet(ids),
            launcher_belief_mass_by_torp_id=dict.fromkeys(ids, 1.0),
        )

    def belief_mass_for_torp_id(self, torp_id: int) -> float:
        mass = self.launcher_belief_mass_by_torp_id.get(torp_id, 0.0)
        if mass <= 0.0:
            return 0.0
        if mass >= 1.0:
            return 1.0
        return float(mass)


@dataclass(frozen=True)
class FleetTorpOverlayDiagnostics:
    applied: bool
    enabled: bool
    belief_set_torp_ids: tuple[int, ...]
    admitted_torp_ids: tuple[int, ...]
    policy_step_id: str
    escape_tier_used: bool
    torp_misalignment_log_penalty: int
    launcher_belief_mass_by_torp_id: Mapping[int, float] = field(default_factory=dict)
    effective_torp_misalignment_log_penalty_by_torp_id: Mapping[int, int] = field(
        default_factory=dict
    )

    def to_payload(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "enabled": self.enabled,
            "beliefSetTorpIds": list(self.belief_set_torp_ids),
            "admittedTorpIds": list(self.admitted_torp_ids),
            "policyStepId": self.policy_step_id,
            "escapeTierUsed": self.escape_tier_used,
            "torpMisalignmentLogPenalty": self.torp_misalignment_log_penalty,
            "launcherBeliefMassByTorpId": {
                str(torp_id): mass
                for torp_id, mass in sorted(self.launcher_belief_mass_by_torp_id.items())
            },
            "effectiveTorpMisalignmentLogPenaltyByTorpId": {
                str(torp_id): penalty
                for torp_id, penalty in sorted(
                    self.effective_torp_misalignment_log_penalty_by_torp_id.items()
                )
            },
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


def overlay_from_fleet_records(records: Iterable[FleetShipRecord]) -> FleetTorpOverlay:
    """Build overlay with flat admission union plus per-torp belief mass (#253)."""
    record_list = list(records)
    belief = launcher_belief_set_from_fleet_records(record_list)
    return FleetTorpOverlay(
        belief_set=belief,
        launcher_belief_mass_by_torp_id=launcher_belief_mass_by_torp_id_from_records(record_list),
    )


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


def effective_torp_misalignment_log_penalty(
    *,
    torp_id: int,
    overlay: FleetTorpOverlay,
    tuning: FleetInferenceTuning,
) -> int:
    """Mass-scaled misalignment: ``round(P * (1 - mass))`` (#253)."""
    base = tuning.torp_misalignment_log_penalty
    if base <= 0:
        return 0
    mass = overlay.belief_mass_for_torp_id(torp_id)
    return round(base * (1.0 - mass))


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
        # Log-probability weights are <= 0; subtract the penalty without a floor.
        adjusted.append(
            replace(
                bucket,
                marginal_weight=bucket.marginal_weight - penalty,
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

    adjusted = dict(probability_buckets)
    for action_id in list(adjusted.keys()):
        if not is_torp_load_action_id(action_id):
            continue
        torp_id = int(action_id.removeprefix(SHIP_TORPS_LOADED_ACTION_PREFIX))
        penalty = effective_torp_misalignment_log_penalty(
            torp_id=torp_id,
            overlay=overlay,
            tuning=tuning,
        )
        if penalty <= 0:
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
    mass_by_torp = {
        torp_id: overlay.belief_mass_for_torp_id(torp_id)
        for torp_id in sorted(overlay.launcher_belief_mass_by_torp_id)
    }
    # Also expose masses for admitted / belief-set ids even when mass map omitted 0s.
    for torp_id in overlay.belief_set.torp_ids | admitted_torp_ids:
        mass_by_torp.setdefault(torp_id, overlay.belief_mass_for_torp_id(torp_id))

    effective_penalties = {
        torp_id: effective_torp_misalignment_log_penalty(
            torp_id=torp_id,
            overlay=overlay,
            tuning=tuning,
        )
        for torp_id in sorted(mass_by_torp)
    }
    return FleetTorpOverlayDiagnostics(
        applied=overlay.enabled,
        enabled=overlay.enabled,
        belief_set_torp_ids=tuple(sorted(overlay.belief_set.torp_ids)),
        admitted_torp_ids=tuple(sorted(admitted_torp_ids)),
        policy_step_id=policy_step.id,
        escape_tier_used=policy_step.id == TORP_ESCAPE_TIER_STEP_ID,
        torp_misalignment_log_penalty=tuning.torp_misalignment_log_penalty,
        launcher_belief_mass_by_torp_id=mass_by_torp,
        effective_torp_misalignment_log_penalty_by_torp_id=effective_penalties,
    )
