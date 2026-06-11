"""Registry-driven aggregate action catalog construction."""

from __future__ import annotations

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSlot,
    AggregateActionSpec,
    CatalogConfig,
    base_bin_bounds_for_action,
    iter_aggregate_action_slots,
    resolved_aggregate_cap,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.prior_weights_catalog import PriorWeightsCatalog
from api.analytics.military_score_inference.scoring import STARBASE_FIGHTER_SCORE_DELTA_2X
from api.models.components import Torpedo


def residual_count_bound(
    observation: InferenceObservation,
    score_delta_2x: int,
    configured_cap: int,
) -> int:
    if score_delta_2x == 0:
        return 0
    if observation.military_delta_2x == 0:
        return 0

    abs_score = abs(score_delta_2x)
    abs_residual = abs(observation.military_delta_2x) + observation.military_partition_slack_2x
    return min(configured_cap, abs_residual // abs_score)


def build_aggregate_actions(
    observation: InferenceObservation,
    config: CatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
    eligible_torp_ids: frozenset[int],
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
) -> tuple[list[CandidateAction], dict[str, tuple[ProbabilityBucket, ...]]]:
    actions: list[CandidateAction] = []
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]] = {}
    fighter_transfer_upper_bound = _fighter_transfer_upper_bound(observation, config)

    for slot in iter_aggregate_action_slots(eligible_torp_ids=eligible_torp_ids):
        _append_slot_catalog_action(
            actions,
            probability_buckets,
            slot=slot,
            observation=observation,
            config=config,
            torpedos_by_id=torpedos_by_id,
            aggregate_allowlist=aggregate_allowlist,
            prior_catalog=prior_catalog,
            fighter_transfer_upper_bound=fighter_transfer_upper_bound,
        )

    return actions, probability_buckets


def _probability_buckets_for_aggregate_action(
    action_id: str,
    prior_catalog: PriorWeightsCatalog,
) -> tuple[ProbabilityBucket, ...] | None:
    bin_bounds = base_bin_bounds_for_action(action_id)
    if bin_bounds is None:
        return None
    return prior_catalog.probability_buckets_for_action(action_id, bin_bounds)


def _append_aggregate_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    action_id: str,
    label: str,
    score_delta_2x: int,
    upper_bound: int,
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
    spec: AggregateActionSpec,
) -> None:
    allowlist_cap = resolved_aggregate_cap(action_id, aggregate_allowlist)
    if allowlist_cap is None:
        return
    capped_upper = min(upper_bound, allowlist_cap)
    if capped_upper <= 0:
        return
    probability_weight = spec.catalog_probability_weight(action_id, prior_catalog)
    actions.append(
        CandidateAction(
            id=action_id,
            label=label,
            score_delta_2x=score_delta_2x,
            upper_bound=capped_upper,
            probability_weight=probability_weight,
        )
    )
    buckets = _probability_buckets_for_aggregate_action(action_id, prior_catalog)
    if buckets is not None:
        probability_buckets[action_id] = buckets


def _fighter_transfer_upper_bound(
    observation: InferenceObservation,
    config: CatalogConfig,
) -> int:
    return min(
        config.max_fighter_transfers,
        residual_count_bound(
            observation,
            STARBASE_FIGHTER_SCORE_DELTA_2X,
            config.max_fighter_transfers,
        ),
    )


def _slot_catalog_label(
    slot: AggregateActionSlot,
    *,
    torpedos_by_id: dict[int, Torpedo],
) -> str | None:
    spec = slot.spec
    if spec.is_template:
        entity_id = slot.entity_id
        if entity_id is None:
            raise ValueError(f"template aggregate slot missing entity id: {slot.action_id!r}")
        torpedo = torpedos_by_id.get(entity_id)
        if torpedo is None:
            return None
        if spec.catalog_label_format is None:
            raise ValueError(f"template aggregate slot missing catalog label: {slot.action_id!r}")
        return spec.catalog_label_format.format(name=torpedo.name)
    return spec.catalog_label


def _slot_score_delta_2x(
    slot: AggregateActionSlot,
    *,
    torpedos_by_id: dict[int, Torpedo],
) -> int | None:
    spec = slot.spec
    if spec.is_template:
        entity_id = slot.entity_id
        if entity_id is None:
            raise ValueError(f"template aggregate slot missing entity id: {slot.action_id!r}")
        torpedo = torpedos_by_id.get(entity_id)
        if torpedo is None:
            return None
        if spec.score_delta_2x_from_cost is None:
            raise ValueError(f"template aggregate slot missing score delta: {slot.action_id!r}")
        return spec.score_delta_2x_from_cost(torpedo.torpedocost)
    if spec.score_delta_2x is None:
        return None
    return spec.score_delta_2x()


def _slot_upper_bound(
    slot: AggregateActionSlot,
    *,
    observation: InferenceObservation,
    config: CatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
    fighter_transfer_upper_bound: int,
) -> int | None:
    spec = slot.spec
    score_delta_2x = _slot_score_delta_2x(slot, torpedos_by_id=torpedos_by_id)
    if score_delta_2x is None:
        return None
    if spec.catalog_config_cap is not None:
        return residual_count_bound(
            observation,
            score_delta_2x,
            spec.catalog_config_cap(config),
        )
    return fighter_transfer_upper_bound


def _append_slot_catalog_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    slot: AggregateActionSlot,
    observation: InferenceObservation,
    config: CatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
    fighter_transfer_upper_bound: int,
) -> None:
    label = _slot_catalog_label(slot, torpedos_by_id=torpedos_by_id)
    if label is None:
        return
    score_delta_2x = _slot_score_delta_2x(slot, torpedos_by_id=torpedos_by_id)
    if score_delta_2x is None:
        return
    upper_bound = _slot_upper_bound(
        slot,
        observation=observation,
        config=config,
        torpedos_by_id=torpedos_by_id,
        fighter_transfer_upper_bound=fighter_transfer_upper_bound,
    )
    if upper_bound is None:
        return
    _append_aggregate_action(
        actions,
        probability_buckets,
        action_id=slot.action_id,
        label=label,
        score_delta_2x=score_delta_2x,
        upper_bound=upper_bound,
        aggregate_allowlist=aggregate_allowlist,
        prior_catalog=prior_catalog,
        spec=slot.spec,
    )
