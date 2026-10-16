"""Score-equivalent combo merge plans and the unsolved CP-SAT model they build."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.constraints import InferenceHardConstraints
from api.analytics.military_score_inference.inference_objective import (
    build_inference_objective_terms,
)
from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo
from api.analytics.military_score_inference.reachable_fittings import reachable_ship_fittings
from api.analytics.military_score_inference.ship_build_combos import (
    is_generic_zero_military_score_combo_id,
)

# Ranking objective domain for the exposed IntVar used by near-best banding.
_RANKING_OBJECTIVE_VAR_LB = -10_000_000
_RANKING_OBJECTIVE_VAR_UB = 1_000_000


@dataclass(frozen=True)
class ComboPins:
    """Seed combo counts and the neighborhood those counts may move within."""

    counts: Mapping[str, int]
    neighborhood: int

    def cache_key(self) -> tuple[object, ...]:
        """Identity of this pin in the tier model cache. Empty counts are unpinned."""
        if not self.counts:
            return ("open",)
        return ("pin", self.neighborhood, tuple(sorted(self.counts.items())))


@dataclass(frozen=True)
class MergedComboCatalog:
    combos: tuple[ShipBuildCombo, ...]
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]]


@dataclass(frozen=True)
class BuiltModel:
    model: cp_model.CpModel
    action_count_vars: dict[str, cp_model.IntVar]
    combo_count_vars: dict[str, cp_model.IntVar]
    objective_var: cp_model.IntVar
    merged_combo_catalog: MergedComboCatalog
    diversity_caps_applied: tuple[dict[str, object], ...]
    catalog_ship_fits: int = 0
    reachable_ship_fits: int = 0


def clone_built_model(built: BuiltModel) -> BuiltModel:
    """Copy a model that has not been solved. IntVar indexes stay valid on the clone."""
    return BuiltModel(
        model=built.model.clone(),
        action_count_vars=built.action_count_vars,
        combo_count_vars=built.combo_count_vars,
        objective_var=built.objective_var,
        merged_combo_catalog=built.merged_combo_catalog,
        diversity_caps_applied=built.diversity_caps_applied,
        catalog_ship_fits=built.catalog_ship_fits,
        reachable_ship_fits=built.reachable_ship_fits,
    )


@dataclass(frozen=True)
class MergeGroup:
    """One CP-SAT combo variable and the labeled members that share its score."""

    members: tuple[ShipBuildCombo, ...]
    representative_index: int
    prototype: ShipBuildCombo


@dataclass(frozen=True)
class CatalogMergePlan:
    """Score-equivalence groups for one catalog, built once per tier.

    Neighborhood pins change merged count bounds only. Group membership and the
    member-id map stay fixed, so later solves reuse this plan.
    """

    groups: tuple[MergeGroup, ...]
    member_group_index: dict[str, int]
    combos_by_id: dict[str, ShipBuildCombo]
    unconstrained: MergedComboCatalog

    def catalog_for_pins(self, pins: ComboPins | None) -> MergedComboCatalog:
        """Merged catalog after a seed pin. Unpinned passes return the shared catalog."""
        if pins is None or not pins.counts:
            return self.unconstrained
        touched = self._groups_touched_by(pins.counts)
        merged: list[ShipBuildCombo] = []
        for index, group in enumerate(self.groups):
            if index not in touched:
                merged.append(replace(group.prototype, lower_bound=0, upper_bound=0))
                continue
            lower_bound, upper_bound = self.merged_count_bounds(group, pins)
            if (
                lower_bound == group.prototype.lower_bound
                and upper_bound == group.prototype.upper_bound
            ):
                merged.append(group.prototype)
                continue
            merged.append(
                replace(group.prototype, lower_bound=lower_bound, upper_bound=upper_bound)
            )
        return MergedComboCatalog(
            combos=tuple(merged),
            members_by_merged_id=self.unconstrained.members_by_merged_id,
        )

    def merged_count_bounds(
        self,
        group: MergeGroup,
        pins: ComboPins | None,
    ) -> tuple[int, int]:
        """Representative lower bound and max member upper bound after a pin."""
        representative = group.members[group.representative_index]
        representative_lower, representative_upper = pinned_member_bounds(representative, pins)
        merged_upper = representative_upper
        if pins is None or not pins.counts:
            return representative_lower, merged_upper
        for member in group.members:
            if member is representative or member.combo_id not in pins.counts:
                continue
            _lower, upper = pinned_member_bounds(member, pins)
            if upper > merged_upper:
                merged_upper = upper
        return representative_lower, merged_upper

    def _groups_touched_by(self, counts: Mapping[str, int]) -> set[int]:
        touched: set[int] = set()
        for combo_id in counts:
            index = self.member_group_index.get(combo_id)
            if index is not None:
                touched.add(index)
        return touched


def pinned_member_bounds(
    combo: ShipBuildCombo,
    pins: ComboPins | None,
) -> tuple[int, int]:
    """Count bounds for one combo under a seed pin.

    With no pins the combo keeps its catalog bounds. A pin closes every other
    combo to zero and holds this combo at the seed count, or within
    ``pins.neighborhood`` of that count when the neighborhood is positive.
    """
    if pins is None or not pins.counts:
        return combo.lower_bound, combo.upper_bound
    if combo.combo_id not in pins.counts:
        return 0, 0
    seed_count = pins.counts[combo.combo_id]
    if pins.neighborhood <= 0:
        return seed_count, seed_count
    lower_bound = max(combo.lower_bound, max(0, seed_count - pins.neighborhood))
    upper_bound = min(combo.upper_bound, seed_count + pins.neighborhood)
    return lower_bound, upper_bound


def _prototype_for_members(members: tuple[ShipBuildCombo, ...]) -> tuple[ShipBuildCombo, int]:
    representative = max(members, key=lambda combo: (combo.probability_weight, combo.combo_id))
    representative_index = members.index(representative)
    if len(members) == 1:
        return representative, representative_index
    merged_id = (
        f"combo_equiv_{representative.score_delta_2x}_"
        f"{representative.warship_delta}_{representative.freighter_delta}"
    )
    prototype = replace(
        representative,
        combo_id=merged_id,
        labels=tuple(label for member in members for label in member.labels),
        probability_weight=max(member.probability_weight for member in members),
        upper_bound=max(member.upper_bound for member in members),
    )
    return prototype, representative_index


def build_catalog_merge_plan(combos: tuple[ShipBuildCombo, ...]) -> CatalogMergePlan:
    """Group score-equivalent combos once. Pins reuse the groups."""
    score_groups: dict[tuple[int, int, int], list[ShipBuildCombo]] = defaultdict(list)
    generic_groups: list[MergeGroup] = []
    for combo in combos:
        if is_generic_zero_military_score_combo_id(combo.combo_id):
            generic_groups.append(
                MergeGroup(members=(combo,), representative_index=0, prototype=combo)
            )
            continue
        score_groups[(combo.score_delta_2x, combo.warship_delta, combo.freighter_delta)].append(
            combo
        )

    groups: list[MergeGroup] = list(generic_groups)
    for members_list in score_groups.values():
        sorted_members = tuple(sorted(members_list, key=lambda combo: combo.combo_id))
        prototype, representative_index = _prototype_for_members(sorted_members)
        groups.append(
            MergeGroup(
                members=sorted_members,
                representative_index=representative_index,
                prototype=prototype,
            )
        )

    member_group_index: dict[str, int] = {}
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]] = {}
    merged: list[ShipBuildCombo] = []
    for index, group in enumerate(groups):
        merged.append(group.prototype)
        members_by_merged_id[group.prototype.combo_id] = group.members
        for member in group.members:
            member_group_index[member.combo_id] = index
    return CatalogMergePlan(
        groups=tuple(groups),
        member_group_index=member_group_index,
        combos_by_id={combo.combo_id: combo for combo in combos},
        unconstrained=MergedComboCatalog(
            combos=tuple(merged),
            members_by_merged_id=members_by_merged_id,
        ),
    )


def merge_score_equivalent_combos(
    combos: tuple[ShipBuildCombo, ...],
) -> MergedComboCatalog:
    """Merge score-equivalent combos for CP-SAT feasibility; members kept for extraction."""
    return build_catalog_merge_plan(combos).unconstrained


def build_model(
    problem: InferenceProblem,
    merged_combo_catalog: MergedComboCatalog,
) -> BuiltModel:
    catalog_ship_fits = len(merged_combo_catalog.combos)
    max_combo_weight = max(
        (combo.probability_weight for combo in merged_combo_catalog.combos),
        default=0,
    )
    reachable = reachable_ship_fittings(problem, merged_combo_catalog.combos)
    if len(reachable) != catalog_ship_fits:
        reachable_ids = {combo.combo_id for combo in reachable}
        merged_combo_catalog = MergedComboCatalog(
            combos=reachable,
            members_by_merged_id={
                combo_id: members
                for combo_id, members in merged_combo_catalog.members_by_merged_id.items()
                if combo_id in reachable_ids
            },
        )
    model = cp_model.CpModel()
    action_count_vars = {
        action.id: model.new_int_var(action.lower_bound, action.upper_bound, action.id)
        for action in problem.aggregate_actions
    }
    combo_count_vars = {
        combo.combo_id: model.new_int_var(combo.lower_bound, combo.upper_bound, combo.combo_id)
        for combo in merged_combo_catalog.combos
    }
    objective_terms = build_inference_objective_terms(
        model,
        problem,
        action_count_vars,
        combo_count_vars,
        ship_build_combos=merged_combo_catalog.combos,
        max_combo_weight=max_combo_weight,
    )

    merged_problem = replace(problem, ship_build_combos=merged_combo_catalog.combos)
    diversity_caps_applied = InferenceHardConstraints.from_problem(merged_problem).add_to_model(
        model,
        merged_problem,
        action_count_vars,
        combo_count_vars,
    )
    objective_var = model.new_int_var(
        _RANKING_OBJECTIVE_VAR_LB,
        _RANKING_OBJECTIVE_VAR_UB,
        "ranking_objective",
    )
    if objective_terms:
        model.add(objective_var == sum(objective_terms))
    else:
        model.add(objective_var == 0)
    model.maximize(objective_var)
    return BuiltModel(
        model=model,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        objective_var=objective_var,
        merged_combo_catalog=merged_combo_catalog,
        diversity_caps_applied=tuple(diversity_caps_applied),
        catalog_ship_fits=catalog_ship_fits,
        reachable_ship_fits=len(merged_combo_catalog.combos),
    )
