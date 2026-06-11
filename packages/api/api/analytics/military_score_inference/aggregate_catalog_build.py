"""Registry-driven aggregate action catalog construction."""

from __future__ import annotations

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSlot,
    AggregateActionSpec,
    CatalogConfig,
    base_bin_bounds_for_action,
    iter_aggregate_action_slots,
    lookup_aggregate_action_spec,
    resolved_aggregate_cap,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.prior_weights import PriorWeightsCatalog
from api.analytics.military_score_inference.scoring import STARBASE_FIGHTER_SCORE_DELTA_2X
from api.models.components import Torpedo

HISTOGRAM_ACTION_CATALOG_PROBABILITY_WEIGHT = 0


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
        if slot.template is not None:
            _append_template_slot_catalog_action(
                actions,
                probability_buckets,
                slot=slot,
                observation=observation,
                config=config,
                torpedos_by_id=torpedos_by_id,
                aggregate_allowlist=aggregate_allowlist,
                prior_catalog=prior_catalog,
            )
        else:
            _append_fixed_slot_catalog_action(
                actions,
                probability_buckets,
                slot=slot,
                observation=observation,
                config=config,
                aggregate_allowlist=aggregate_allowlist,
                prior_catalog=prior_catalog,
                fighter_transfer_upper_bound=fighter_transfer_upper_bound,
            )

    return actions, probability_buckets


def _counts_aggregate_probability_weight(
    action_id: str,
    prior_catalog: PriorWeightsCatalog,
) -> int:
    prior_weight = prior_catalog.aggregate_probability_weight(action_id)
    if prior_weight is None:
        raise ValueError(
            f"incomplete prior: missing counts aggregate weight for action {action_id!r}"
        )
    return prior_weight


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
) -> None:
    allowlist_cap = resolved_aggregate_cap(action_id, aggregate_allowlist)
    if allowlist_cap is None:
        return
    capped_upper = min(upper_bound, allowlist_cap)
    if capped_upper <= 0:
        return
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        raise ValueError(f"unknown aggregate action {action_id!r}")
    if spec.prior_shape == "histogram":
        probability_weight = HISTOGRAM_ACTION_CATALOG_PROBABILITY_WEIGHT
    elif spec.prior_shape == "counts":
        probability_weight = _counts_aggregate_probability_weight(action_id, prior_catalog)
    else:
        raise ValueError(f"unknown prior_shape {spec.prior_shape!r} for action {action_id!r}")
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


def _append_catalog_spec_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    action_id: str,
    spec: AggregateActionSpec,
    upper_bound: int,
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
) -> None:
    score_delta_2x = spec.score_delta_2x
    if score_delta_2x is None:
        return
    _append_aggregate_action(
        actions,
        probability_buckets,
        action_id=action_id,
        label=spec.catalog_label,
        score_delta_2x=score_delta_2x(),
        upper_bound=upper_bound,
        aggregate_allowlist=aggregate_allowlist,
        prior_catalog=prior_catalog,
    )


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


def _fixed_action_upper_bound(
    spec: AggregateActionSpec,
    *,
    observation: InferenceObservation,
    config: CatalogConfig,
    fighter_transfer_upper_bound: int,
) -> int | None:
    score_delta_2x = spec.score_delta_2x
    if score_delta_2x is None:
        return None
    if spec.catalog_config_cap is not None:
        return residual_count_bound(
            observation,
            score_delta_2x(),
            spec.catalog_config_cap(config),
        )
    return fighter_transfer_upper_bound


def _append_fixed_slot_catalog_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    slot: AggregateActionSlot,
    observation: InferenceObservation,
    config: CatalogConfig,
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
    fighter_transfer_upper_bound: int,
) -> None:
    upper_bound = _fixed_action_upper_bound(
        slot.spec,
        observation=observation,
        config=config,
        fighter_transfer_upper_bound=fighter_transfer_upper_bound,
    )
    if upper_bound is None:
        return
    _append_catalog_spec_action(
        actions,
        probability_buckets,
        action_id=slot.action_id,
        spec=slot.spec,
        upper_bound=upper_bound,
        aggregate_allowlist=aggregate_allowlist,
        prior_catalog=prior_catalog,
    )


def _append_template_slot_catalog_action(
    actions: list[CandidateAction],
    probability_buckets: dict[str, tuple[ProbabilityBucket, ...]],
    *,
    slot: AggregateActionSlot,
    observation: InferenceObservation,
    config: CatalogConfig,
    torpedos_by_id: dict[int, Torpedo],
    aggregate_allowlist: dict[str, int],
    prior_catalog: PriorWeightsCatalog,
) -> None:
    template = slot.template
    torpedo_id = slot.entity_id
    if template is None or torpedo_id is None:
        raise ValueError(f"template aggregate slot missing template metadata: {slot.action_id!r}")
    torpedo = torpedos_by_id.get(torpedo_id)
    if torpedo is None:
        return
    configured_cap = template.catalog_config_cap(config)
    score_delta_2x = template.score_delta_2x_from_cost(torpedo.torpedocost)
    _append_aggregate_action(
        actions,
        probability_buckets,
        action_id=slot.action_id,
        label=template.catalog_label_format.format(name=torpedo.name),
        score_delta_2x=score_delta_2x,
        upper_bound=residual_count_bound(
            observation,
            score_delta_2x,
            configured_cap,
        ),
        aggregate_allowlist=aggregate_allowlist,
        prior_catalog=prior_catalog,
    )
