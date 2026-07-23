"""Homogeneous per-axis degrade → aggregate rewrite probe (no full-catalog CP-SAT).

Rewrites ship-only held exacts by degrading whole axes (engine / beam / launcher type
× slot count) to tech≤ replacements and funding an aggregate (v1: ship torp ammo)
with the freed military score. Mixed component variants on one ship are impossible
by construction.

Admissions require catalog combo resolution and hard equality checks -- synthetic
``degrade_probe:`` combo ids are never emitted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.actions import ActionCatalog, build_inference_problem
from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    is_torp_load_action_id,
)
from api.analytics.military_score_inference.constraints import (
    solution_satisfies_exact_hard_equalities,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x
from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_id
from api.analytics.military_score_inference.solver import solution_rank_objective
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo

AxisName = Literal["engine", "beam", "launcher"]

PROBE_STEP_IDS = frozenset({"admit_ship_torpedoes"})


def torpedo_id_from_ship_torps_loaded_action_id(action_id: str) -> int | None:
    if not is_torp_load_action_id(action_id):
        return None
    return int(action_id.removeprefix(SHIP_TORPS_LOADED_ACTION_PREFIX))


@dataclass(frozen=True)
class _AxisFit:
    ship_index: int
    axis: AxisName
    slot_count: int
    original_id: int
    original_tech: int
    original_score_2x: int
    # (id, tech, score_2x) with score_2x < original_score_2x and tech <= original
    variants: tuple[tuple[int, int, int], ...]


class _AxisComponent(Protocol):
    id: int
    techlevel: int
    tritanium: int
    duranium: int
    molybdenum: int


def _component_minerals(component: _AxisComponent) -> int:
    return component.tritanium + component.duranium + component.molybdenum


def _axis_score_2x(*, mc_cost: int, minerals: int, slot_count: int, ship_count: int) -> int:
    per_ship = ship_construction_score_delta_2x(
        mc_cost * slot_count,
        minerals * slot_count,
    )
    return per_ship * ship_count


def _axis_fit_for_component[T: _AxisComponent](
    *,
    ship_index: int,
    axis: AxisName,
    slot_count: int,
    ship_count: int,
    original: T,
    candidates: Mapping[int, T],
    eligible_ids: frozenset[int],
    mc_cost: Callable[[T], int],
) -> _AxisFit:
    original_score = _axis_score_2x(
        mc_cost=mc_cost(original),
        minerals=_component_minerals(original),
        slot_count=slot_count,
        ship_count=ship_count,
    )
    variants: list[tuple[int, int, int]] = []
    for candidate in candidates.values():
        if candidate.id not in eligible_ids:
            continue
        if candidate.techlevel > original.techlevel or candidate.id == original.id:
            continue
        score = _axis_score_2x(
            mc_cost=mc_cost(candidate),
            minerals=_component_minerals(candidate),
            slot_count=slot_count,
            ship_count=ship_count,
        )
        if score < original_score:
            variants.append((candidate.id, candidate.techlevel, score))
    return _AxisFit(
        ship_index=ship_index,
        axis=axis,
        slot_count=slot_count,
        original_id=original.id,
        original_tech=original.techlevel,
        original_score_2x=original_score,
        variants=tuple(variants),
    )


def _axes_for_ship_build(
    ship_build: InferenceSolutionShipBuild,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    eligible_engine_ids: frozenset[int],
    eligible_beam_ids: frozenset[int],
    eligible_torp_ids: frozenset[int],
    ship_index: int,
) -> list[_AxisFit]:
    if ship_build.hull_id is None or ship_build.count <= 0:
        return []
    hull = hulls_by_id.get(ship_build.hull_id)
    if hull is None:
        return []
    ship_count = ship_build.count
    axes: list[_AxisFit] = []
    if ship_build.engine_id is not None and hull.engines > 0:
        engine = engines_by_id.get(ship_build.engine_id)
        if engine is not None:
            axes.append(
                _axis_fit_for_component(
                    ship_index=ship_index,
                    axis="engine",
                    slot_count=hull.engines,
                    ship_count=ship_count,
                    original=engine,
                    candidates=engines_by_id,
                    eligible_ids=eligible_engine_ids,
                    mc_cost=lambda component: component.cost,
                )
            )
    if ship_build.beam_id is not None and ship_build.beam_count > 0:
        beam = beams_by_id.get(ship_build.beam_id)
        if beam is not None:
            axes.append(
                _axis_fit_for_component(
                    ship_index=ship_index,
                    axis="beam",
                    slot_count=ship_build.beam_count,
                    ship_count=ship_count,
                    original=beam,
                    candidates=beams_by_id,
                    eligible_ids=eligible_beam_ids,
                    mc_cost=lambda component: component.cost,
                )
            )
    if ship_build.torp_id is not None and ship_build.launcher_count > 0:
        torpedo = torpedos_by_id.get(ship_build.torp_id)
        if torpedo is not None:
            axes.append(
                _axis_fit_for_component(
                    ship_index=ship_index,
                    axis="launcher",
                    slot_count=ship_build.launcher_count,
                    ship_count=ship_count,
                    original=torpedo,
                    candidates=torpedos_by_id,
                    eligible_ids=eligible_torp_ids,
                    mc_cost=lambda component: component.launchercost,
                )
            )
    return axes


def _resolve_ship_build_to_catalog_combo(
    *,
    hull_id: int | None,
    engine_id: int | None,
    beam_id: int | None,
    torp_id: int | None,
    beam_count: int,
    launcher_count: int,
    count: int,
    combos_by_id: dict[str, ShipBuildCombo],
) -> InferenceSolutionShipBuild | None:
    if hull_id is None or engine_id is None:
        return None
    combo_id = ship_build_combo_id(
        hull_id=hull_id,
        engine_id=engine_id,
        beam_id=beam_id,
        torp_id=torp_id,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )
    combo = combos_by_id.get(combo_id)
    if combo is None:
        return None
    return InferenceSolutionShipBuild(
        combo_id=combo.combo_id,
        label=combo.labels[0] if combo.labels else combo.combo_id,
        count=count,
        hull_id=combo.hull_id,
        engine_id=combo.engine_id,
        beam_id=combo.beam_id,
        torp_id=combo.torp_id,
        beam_count=combo.beam_count,
        launcher_count=combo.launcher_count,
    )


def _apply_axis_choices(
    ship_builds: tuple[InferenceSolutionShipBuild, ...],
    chosen_variant_id: dict[tuple[int, AxisName], int | None],
    *,
    combos_by_id: dict[str, ShipBuildCombo],
) -> tuple[InferenceSolutionShipBuild, ...] | None:
    rebuilt: list[InferenceSolutionShipBuild] = []
    for index, ship_build in enumerate(ship_builds):
        engine_id = ship_build.engine_id
        beam_id = ship_build.beam_id
        torp_id = ship_build.torp_id
        engine_choice = chosen_variant_id.get((index, "engine"))
        beam_choice = chosen_variant_id.get((index, "beam"))
        launcher_choice = chosen_variant_id.get((index, "launcher"))
        if engine_choice is not None:
            engine_id = engine_choice
        if beam_choice is not None:
            beam_id = beam_choice
        if launcher_choice is not None:
            torp_id = launcher_choice
        resolved = _resolve_ship_build_to_catalog_combo(
            hull_id=ship_build.hull_id,
            engine_id=engine_id,
            beam_id=beam_id,
            torp_id=torp_id,
            beam_count=ship_build.beam_count,
            launcher_count=ship_build.launcher_count,
            count=ship_build.count,
            combos_by_id=combos_by_id,
        )
        if resolved is None:
            return None
        rebuilt.append(resolved)
    return tuple(rebuilt)


def _solve_degrade_for_aggregate(
    axes: list[_AxisFit],
    *,
    ammo_score_2x: int,
    max_count: int,
) -> tuple[int, dict[tuple[int, AxisName], int | None]] | None:
    """Return (aggregate_count, axis→variant_id|None) or None when infeasible."""
    if ammo_score_2x <= 0 or max_count <= 0 or not axes:
        return None
    if not any(axis.variants for axis in axes):
        return None

    model = cp_model.CpModel()
    count_var = model.new_int_var(1, max_count, "ammo_count")
    gap_terms: list[cp_model.LinearExprT] = []
    degraded_flags: list[cp_model.BoolVarT] = []
    choice_vars: dict[tuple[int, AxisName], list[tuple[int, cp_model.BoolVarT]]] = {}

    for axis in axes:
        keep = model.new_bool_var(f"keep_s{axis.ship_index}_{axis.axis}")
        variant_bools: list[cp_model.BoolVarT] = []
        pairs: list[tuple[int, cp_model.BoolVarT]] = []
        for variant_id, _tech, variant_score in axis.variants:
            use = model.new_bool_var(f"use_s{axis.ship_index}_{axis.axis}_{variant_id}")
            variant_bools.append(use)
            pairs.append((variant_id, use))
            freed = axis.original_score_2x - variant_score
            gap_terms.append(use * freed)
        if not variant_bools:
            model.add(keep == 1)
            choice_vars[(axis.ship_index, axis.axis)] = []
            continue
        model.add(sum(variant_bools) + keep == 1)
        degraded = model.new_bool_var(f"degraded_s{axis.ship_index}_{axis.axis}")
        model.add(keep == 0).only_enforce_if(degraded)
        model.add(keep == 1).only_enforce_if(degraded.negated())
        degraded_flags.append(degraded)
        choice_vars[(axis.ship_index, axis.axis)] = pairs

    if not degraded_flags or not gap_terms:
        return None
    model.add(sum(degraded_flags) >= 1)
    model.add(sum(gap_terms) == count_var * ammo_score_2x)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.25
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    chosen: dict[tuple[int, AxisName], int | None] = {}
    for key, pairs in choice_vars.items():
        selected: int | None = None
        for variant_id, use in pairs:
            if solver.value(use) == 1:
                selected = variant_id
                break
        chosen[key] = selected
    return int(solver.value(count_var)), chosen


def probe_degrade_aggregate_rewrites(
    held_solutions: list[InferenceSolution] | tuple[InferenceSolution, ...],
    *,
    turn: TurnInfo,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    max_solutions: int = 20,
) -> list[InferenceSolution]:
    """Generate catalog-resolved C' + torp-ammo rewrites from ship-only held exacts.

    Only emits solutions that resolve to catalog combo ids and satisfy hard
    equalities against ``observation``.
    """
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    if not combos_by_id:
        return []

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}
    # Restrict degrade targets to components that appear on at least one catalog combo
    # so rewrites can resolve (avoid synthetic combo ids).
    eligible_engine_ids = frozenset(combo.engine_id for combo in catalog.ship_build_combos)
    eligible_beam_ids = frozenset(
        combo.beam_id for combo in catalog.ship_build_combos if combo.beam_id is not None
    )
    eligible_torp_ids = frozenset(
        combo.torp_id for combo in catalog.ship_build_combos if combo.torp_id is not None
    )

    torp_actions: list[CandidateAction] = [
        action
        for action in catalog.aggregate_actions
        if is_torp_load_action_id(action.id)
        and action.score_delta_2x > 0
        and action.upper_bound > 0
    ]
    if not torp_actions:
        return []

    problem = build_inference_problem(observation, catalog)
    out: list[InferenceSolution] = []
    for held in held_solutions:
        if held.actions or not held.ship_builds:
            continue
        if not solution_satisfies_exact_hard_equalities(held, observation, catalog):
            # Only rewrite held exacts; otherwise gap funding does not preserve truth.
            continue
        axes: list[_AxisFit] = []
        for ship_index, ship_build in enumerate(held.ship_builds):
            axes.extend(
                _axes_for_ship_build(
                    ship_build,
                    hulls_by_id=hulls_by_id,
                    engines_by_id=engines_by_id,
                    beams_by_id=beams_by_id,
                    torpedos_by_id=torpedos_by_id,
                    eligible_engine_ids=eligible_engine_ids,
                    eligible_beam_ids=eligible_beam_ids,
                    eligible_torp_ids=eligible_torp_ids,
                    ship_index=ship_index,
                )
            )
        if not axes:
            continue
        for action in torp_actions:
            solved = _solve_degrade_for_aggregate(
                axes,
                ammo_score_2x=action.score_delta_2x,
                max_count=action.upper_bound,
            )
            if solved is None:
                continue
            count, chosen = solved
            new_builds = _apply_axis_choices(
                held.ship_builds,
                chosen,
                combos_by_id=combos_by_id,
            )
            if new_builds is None:
                continue
            candidate = InferenceSolution(
                objective_value=0,
                actions=(
                    InferenceSolutionAction(
                        action_id=action.id,
                        label=action.label,
                        count=count,
                    ),
                ),
                ship_builds=new_builds,
            )
            if not solution_satisfies_exact_hard_equalities(candidate, observation, catalog):
                continue
            candidate = InferenceSolution(
                objective_value=solution_rank_objective(problem, candidate),
                actions=candidate.actions,
                ship_builds=candidate.ship_builds,
            )
            out.append(candidate)
            if len(out) >= max_solutions:
                return out
    return out


def should_run_degrade_aggregate_probe(policy_step_id: str) -> bool:
    return policy_step_id in PROBE_STEP_IDS


__all__ = [
    "PROBE_STEP_IDS",
    "probe_degrade_aggregate_rewrites",
    "should_run_degrade_aggregate_probe",
    "torpedo_id_from_ship_torps_loaded_action_id",
]
