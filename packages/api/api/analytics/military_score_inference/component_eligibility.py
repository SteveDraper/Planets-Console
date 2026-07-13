"""Shared hull and component eligibility helpers for military score inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.hull_catalog_mask import (
    ResolvedHullCatalogMask,
    default_enabled_hull_ids_for_player,
)
from api.analytics.military_score_inference.inference_turn_lookup import (
    parse_component_id_csv,
    player_by_id,
)
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo


@dataclass(frozen=True)
class TurnCatalogContext:
    hulls_by_id: dict[int, Hull]
    engines_by_id: dict[int, Engine]
    beams_by_id: dict[int, Beam]
    torpedos_by_id: dict[int, Torpedo]
    buildable_hull_ids: frozenset[int]
    eligible_engine_ids: frozenset[int]
    eligible_beam_ids: frozenset[int]
    eligible_torp_ids: frozenset[int]


def buildable_hull_ids_for_player(
    turn: TurnInfo,
    player_id: int,
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> frozenset[int]:
    """Return hull ids buildable for the inference target player on this turn snapshot."""
    catalog_hull_ids = frozenset(hull.id for hull in turn.hulls)
    if resolved_mask is not None:
        return resolved_mask.effective_enabled_hull_ids & catalog_hull_ids
    return default_enabled_hull_ids_for_player(turn, player_id)


def eligible_component_ids_for_player(
    *,
    active_component_csv: str,
    turn_catalog_ids: frozenset[int],
) -> frozenset[int]:
    """Return active components intersected with the turn catalog, jumping when active is empty."""
    active_ids = parse_component_id_csv(active_component_csv)
    if not active_ids:
        return turn_catalog_ids
    return active_ids & turn_catalog_ids


def _apply_component_id_allowlist(
    eligible_ids: frozenset[int],
    component_filter: ComponentFilter,
) -> frozenset[int]:
    if not component_filter.component_ids:
        return eligible_ids
    allowed = frozenset(component_filter.component_ids)
    return eligible_ids & allowed


def _apply_include_component_ids(
    eligible_ids: frozenset[int],
    component_filter: ComponentFilter,
    *,
    candidate_ids: frozenset[int],
) -> frozenset[int]:
    if not component_filter.include_component_ids:
        return eligible_ids
    return eligible_ids | (frozenset(component_filter.include_component_ids) & candidate_ids)


def _component_ids_for_tech_levels(
    components_by_id: dict[int, Hull | Engine | Beam | Torpedo],
    *,
    tech_levels: tuple[int, ...],
) -> frozenset[int]:
    return frozenset(
        component_id
        for component_id, component in components_by_id.items()
        if component.techlevel in tech_levels
    )


def eligible_hull_ids_for_filter(
    turn: TurnInfo,
    player_id: int,
    hull_filter: ComponentFilter,
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> frozenset[int]:
    """Resolve hull ids from a policy ``filters.hulls`` entry."""
    buildable_hull_ids = buildable_hull_ids_for_player(
        turn,
        player_id,
        resolved_mask=resolved_mask,
    )
    if hull_filter.all:
        eligible_ids = buildable_hull_ids
    else:
        hulls_by_id = {hull.id: hull for hull in turn.hulls}
        eligible_ids = frozenset(
            hull_id
            for hull_id in buildable_hull_ids
            if hull_id in hulls_by_id and hulls_by_id[hull_id].techlevel in hull_filter.tech_levels
        )
    eligible_ids = _apply_include_component_ids(
        eligible_ids,
        hull_filter,
        candidate_ids=buildable_hull_ids,
    )
    return _apply_component_id_allowlist(eligible_ids, hull_filter)


def eligible_component_ids_for_filter(
    component_filter: ComponentFilter,
    *,
    active_component_csv: str,
    components_by_id: dict[int, Engine | Beam | Torpedo],
) -> frozenset[int]:
    """Resolve engine, beam, or launcher torpedo ids from a policy filter entry."""
    turn_catalog_ids = frozenset(components_by_id)
    if component_filter.all:
        eligible_ids = eligible_component_ids_for_player(
            active_component_csv=active_component_csv,
            turn_catalog_ids=turn_catalog_ids,
        )
    else:
        eligible_ids = _component_ids_for_tech_levels(
            components_by_id,
            tech_levels=component_filter.tech_levels,
        )
    eligible_ids = _apply_include_component_ids(
        eligible_ids,
        component_filter,
        candidate_ids=turn_catalog_ids,
    )
    return _apply_component_id_allowlist(eligible_ids, component_filter)


def turn_catalog_context_for_policy_step(
    turn: TurnInfo,
    player_id: int,
    policy_step: InferenceTierPolicyStep,
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> TurnCatalogContext:
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}
    player = player_by_id(turn, player_id)
    filters: InferenceCatalogFilters = policy_step.filters

    return TurnCatalogContext(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=eligible_hull_ids_for_filter(
            turn,
            player_id,
            filters.hulls,
            resolved_mask=resolved_mask,
        ),
        eligible_engine_ids=eligible_component_ids_for_filter(
            filters.engines,
            active_component_csv=player.activeengines,
            components_by_id=engines_by_id,
        ),
        eligible_beam_ids=eligible_component_ids_for_filter(
            filters.beams,
            active_component_csv=player.activebeams,
            components_by_id=beams_by_id,
        ),
        eligible_torp_ids=eligible_component_ids_for_filter(
            filters.launchers,
            active_component_csv=player.activetorps,
            components_by_id=torpedos_by_id,
        ),
    )


def turn_catalog_context_for_player(turn: TurnInfo, player_id: int) -> TurnCatalogContext:
    """Full active-or-jump eligibility using the final policy step semantics."""
    from api.analytics.military_score_inference.tier_policy import resolve_tier_policies

    policy_steps = resolve_tier_policies()
    return turn_catalog_context_for_policy_step(turn, player_id, policy_steps[-1])
