"""Registry-driven aggregate action catalog construction."""

from __future__ import annotations

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateCatalogCaps,
    AggregatePriorFields,
    FixedAggregateSlot,
    TemplateAggregateSlot,
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
    config: AggregateCatalogCaps,
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
    prior_fields: AggregatePriorFields,
    prior_catalog: PriorWeightsCatalog,
) -> tuple[ProbabilityBucket, ...] | None:
    if prior_fields.bin_bounds is None:
        return None
    return prior_catalog.probability_buckets_for_action(action_id, prior_fields.bin_bounds)


def _aggregate_action_probability_weight(
    action_id: str,
    prior_fields: AggregatePriorFields,
    prior_catalog: PriorWeightsCatalog,
) -> int:
    if prior_fields.prior_shape == "histogram":
        return 0
    if prior_fields.prior_shape == "counts":
        prior_weight = prior_catalog.aggregate_probability_weight(action_id)
        if prior_weight is None:
            raise ValueError(
                f"incomplete prior: missing counts aggregate weight for action {action_id!r}"
            )
        return prior_weight
    raise ValueError(f"unknown prior_shape {prior_fields.prior_shape!r} for action {action_id!r}")


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
    prior_fields: AggregatePriorFields,
) -> None:
    allowlist_cap = resolved_aggregate_cap(action_id, aggregate_allowlist)
    if allowlist_cap is None:
        return
    capped_upper = min(upper_bound, allowlist_cap)
    if capped_upper <= 0:
        return
    probability_weight = _aggregate_action_probability_weight(
        action_id,
        prior_fields,
        prior_catalog,
    )
    actions.append(
        CandidateAction(
            id=action_id,
            label=label,
            score_delta_2x=score_delta_2x,
            upper_bound=capped_upper,
            probability_weight=probability_weight,
        )
    )
    buckets = _probability_buckets_for_aggregate_action(action_id, prior_fields, prior_catalog)
    if buckets is not None:
        probability_buckets[action_id] = buckets


def _fighter_transfer_upper_bound(
    observation: InferenceObservation,
    config: AggregateCatalogCaps,
) -> int:
    return min(
        config.max_fighter_transfers,
        residual_count_bound(
            observation,
            STARBASE_FIGHTER_SCORE_DELTA_2X,
            config.max_fighter_transfers,
        ),
    )


def _upper_bound_for_fixed_slot(
    slot: FixedAggregateSlot,
    *,
    observation: InferenceObservation,
    config: AggregateCatalogCaps,
    fighter_transfer_upper_bound: int,
) -> int:
    if slot.spec.catalog_config_cap is not None:
        return residual_count_bound(
            observation,
            slot.score_delta_2x,
            slot.spec.catalog_config_cap(config),
        )
    return fighter_transfer_upper_bound


def _append_slot_catalog_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    slot: FixedAggregateSlot | TemplateAggregateSlot,
    observation: InferenceObservation,
    config: AggregateCatalogCaps,
    torpedos_by_id: dict[int, Torpedo],
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
    fighter_transfer_upper_bound: int,
) -> None:
    if isinstance(slot, FixedAggregateSlot):
        _append_aggregate_action(
            actions,
            probability_buckets,
            action_id=slot.action_id,
            label=slot.catalog_label,
            score_delta_2x=slot.score_delta_2x,
            upper_bound=_upper_bound_for_fixed_slot(
                slot,
                observation=observation,
                config=config,
                fighter_transfer_upper_bound=fighter_transfer_upper_bound,
            ),
            aggregate_allowlist=aggregate_allowlist,
            prior_catalog=prior_catalog,
            prior_fields=slot.spec,
        )
        return

    torpedo = torpedos_by_id.get(slot.entity_id)
    if torpedo is None:
        return
    if slot.spec.score_delta_2x_from_cost is None:
        raise ValueError(f"template aggregate slot missing score delta: {slot.action_id!r}")
    if slot.spec.catalog_config_cap is None:
        raise ValueError(f"template aggregate slot missing config cap: {slot.action_id!r}")
    score_delta_2x = slot.spec.score_delta_2x_from_cost(torpedo.torpedocost)
    _append_aggregate_action(
        actions,
        probability_buckets,
        action_id=slot.action_id,
        label=slot.spec.catalog_label_format.format(name=torpedo.name),
        score_delta_2x=score_delta_2x,
        upper_bound=residual_count_bound(
            observation,
            score_delta_2x,
            slot.spec.catalog_config_cap(config),
        ),
        aggregate_allowlist=aggregate_allowlist,
        prior_catalog=prior_catalog,
        prior_fields=slot.spec,
    )
