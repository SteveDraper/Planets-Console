"""Timing probe for opt-in scores outlier reproductions.

Records model-build, solve, and span samples while a stored row runs. The
probe patches solver entry points for the duration of one reproduction and
restores them afterward. It does not change the search.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from api.analytics.military_score_inference import (
    analytic,
    catalog_model,
    inference_api_payload,
    inference_row_runner,
    policy_ladder,
    policy_ladder_tier_step,
    row_complete_factory,
    ship_first_family,
    solver,
    worthwhile_remainder_bound,
)
from api.analytics.military_score_inference import (
    near_best_structural_search as near_best,
)
from api.analytics.military_score_inference.prior_mining import mine_stock
from ortools.sat.python import cp_model

_active_tier: ContextVar[str] = ContextVar("outlier_repro_tier", default="")
_active_phase: ContextVar[str] = ContextVar("outlier_repro_phase", default="other")


@dataclass
class BuildSample:
    tier: str
    phase: str
    wall_seconds: float
    variables: int
    constraints: int
    combos: int


@dataclass
class SolveSample:
    tier: str
    phase: str
    wall_seconds: float
    deterministic_time: float
    status: str
    booleans: int
    conflicts: int
    branches: int


@dataclass
class SpanSample:
    tier: str
    name: str
    wall_seconds: float


@dataclass
class TierSample:
    index: int
    tier_id: str
    wall_seconds: float
    outcome: str
    combo_count: int
    stopped_reason: str
    solve_wall_seconds: float
    deterministic_time: float
    structural_hits: int


@dataclass
class OutlierReproduction:
    fleet_input_status: str
    record_count: int
    military_delta_2x: int = 0
    warship_delta: int = 0
    freighter_delta: int = 0
    starbases_owned: int = 0
    tiers: list[TierSample] = field(default_factory=list)
    builds: list[BuildSample] = field(default_factory=list)
    solves: list[SolveSample] = field(default_factory=list)
    spans: list[SpanSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    band_callbacks: int = 0
    band_callback_seconds: float = 0.0
    solution_action_ids: list[tuple[str, ...]] = field(default_factory=list)
    solution_families: list[str | None] = field(default_factory=list)

    def tier(self, index: int) -> TierSample | None:
        for sample in self.tiers:
            if sample.index == index:
                return sample
        return None


class PhaseProbe:
    """Time model builds and ``CpSolver.solve`` without changing the search."""

    def __init__(self, report: OutlierReproduction) -> None:
        self._report = report
        self._installed = False
        self._original_solve = cp_model.CpSolver.solve
        self._solver_module = None
        self._original_build = None
        self._tier_step_module = None
        self._original_probe = None
        self._original_solve_problem = None
        self._original_catalog = None
        self._original_merge = None
        self._original_expand = None
        self._family_module = None
        self._original_step_leftover = None
        self._original_family_leftover = None
        self._original_non_torp = None

    @contextmanager
    def measure_tier(self, tier_index: int, tier_id: str) -> Iterator[None]:
        """Bind the active tier label for timed builds and solves in this step."""
        token = _active_tier.set(f"{tier_index}:{tier_id}")
        try:
            yield
        finally:
            _active_tier.reset(token)

    def install(self) -> None:
        report = self._report
        original_solve = self._original_solve

        def timed_solve(solver, model, *args, **kwargs):
            started = time.perf_counter()
            status = original_solve(solver, model, *args, **kwargs)
            wall_seconds = time.perf_counter() - started
            try:
                deterministic_time = float(solver.deterministic_time)
            except RuntimeError, TypeError, ValueError:
                deterministic_time = 0.0
            try:
                status_name = solver.status_name(status)
            except RuntimeError, TypeError, ValueError:
                status_name = str(status)
            report.solves.append(
                SolveSample(
                    tier=_active_tier.get(),
                    phase=_active_phase.get(),
                    wall_seconds=wall_seconds,
                    deterministic_time=deterministic_time,
                    status=status_name,
                    booleans=_solver_int(solver, "num_booleans"),
                    conflicts=_solver_int(solver, "num_conflicts"),
                    branches=_solver_int(solver, "num_branches"),
                )
            )
            return status

        original_build = catalog_model.build_model

        def timed_build(problem, merged_combo_catalog):
            started = time.perf_counter()
            built = original_build(problem, merged_combo_catalog)
            wall_seconds = time.perf_counter() - started
            proto = built.model.proto
            report.builds.append(
                BuildSample(
                    tier=_active_tier.get(),
                    phase=_active_phase.get(),
                    wall_seconds=wall_seconds,
                    variables=len(proto.variables),
                    constraints=len(proto.constraints),
                    combos=len(problem.ship_build_combos),
                )
            )
            return built

        original_probe = policy_ladder_tier_step.probe_degrade_aggregate_rewrites

        def timed_probe(*args, **kwargs):
            token = _active_phase.set("degrade")
            try:
                return original_probe(*args, **kwargs)
            finally:
                _active_phase.reset(token)

        original_solve_problem = policy_ladder_tier_step.solve_inference_problem

        def timed_solve_problem(*args, **kwargs):
            token = _active_phase.set("structural")
            started = time.perf_counter()
            try:
                return original_solve_problem(*args, **kwargs)
            finally:
                report.spans.append(
                    SpanSample(
                        tier=_active_tier.get(),
                        name="solve_problem",
                        wall_seconds=time.perf_counter() - started,
                    )
                )
                _active_phase.reset(token)

        def timed_span(name: str, fn):
            def wrapped(*args, **kwargs):
                started = time.perf_counter()
                try:
                    return fn(*args, **kwargs)
                finally:
                    report.spans.append(
                        SpanSample(
                            tier=_active_tier.get(),
                            name=name,
                            wall_seconds=time.perf_counter() - started,
                        )
                    )

            return wrapped

        original_catalog = policy_ladder_tier_step.build_action_catalog_from_turn

        def timed_catalog(*args, **kwargs):
            started = time.perf_counter()
            catalog = original_catalog(*args, **kwargs)
            report.spans.append(
                SpanSample(
                    tier=_active_tier.get(),
                    name="catalog",
                    wall_seconds=time.perf_counter() - started,
                )
            )
            actions = ", ".join(
                f"{action.id} score={action.score_delta_2x} ub={action.upper_bound}"
                for action in catalog.aggregate_actions
            )
            report.notes.append(
                f"{_active_tier.get()} combos={len(catalog.ship_build_combos)} "
                f"aggregates={len(catalog.aggregate_actions)} [{actions}]"
            )
            return catalog

        original_merge = catalog_model.merge_score_equivalent_combos
        original_expand = solver.expand_structural_hits_to_top_k
        cp_model.CpSolver.solve = timed_solve
        catalog_model.build_model = timed_build
        policy_ladder_tier_step.probe_degrade_aggregate_rewrites = timed_probe
        policy_ladder_tier_step.solve_inference_problem = timed_solve_problem
        policy_ladder_tier_step.build_action_catalog_from_turn = timed_catalog
        catalog_model.merge_score_equivalent_combos = timed_span("merge", original_merge)
        solver.expand_structural_hits_to_top_k = timed_span("expand", original_expand)
        original_build_problem = policy_ladder_tier_step.build_inference_problem
        original_validate = solver._validate_problem
        original_collect = solver.collect_near_best_structural_hits
        band_collector = near_best._ObjectiveBandCollector
        original_on_solution = band_collector.on_solution_callback

        def timed_on_solution(callback_self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return original_on_solution(callback_self, *args, **kwargs)
            finally:
                report.band_callbacks += 1
                report.band_callback_seconds += time.perf_counter() - started

        band_collector.on_solution_callback = timed_on_solution
        self._band_collector_type = band_collector
        self._original_on_solution = original_on_solution

        original_read_combos = near_best._read_combo_counts
        original_seed_cuts = near_best.seed_no_good_cuts_for_held_solutions
        policy_ladder_tier_step.build_inference_problem = timed_span(
            "build_problem",
            original_build_problem,
        )
        solver._validate_problem = timed_span("validate", original_validate)
        solver.collect_near_best_structural_hits = timed_span("collect_hits", original_collect)
        near_best._read_combo_counts = timed_span("read_combos", original_read_combos)
        near_best.seed_no_good_cuts_for_held_solutions = timed_span(
            "seed_cuts",
            original_seed_cuts,
        )
        original_step_leftover = policy_ladder_tier_step.leftover_military_2x
        original_family_leftover = ship_first_family.leftover_military_2x
        original_non_torp = ship_first_family.non_torp_military_2x
        original_step_lookups = policy_ladder_tier_step.catalog_score_lookups
        original_ladder_lookups = policy_ladder.catalog_score_lookups
        original_payload_lookups = inference_api_payload.catalog_score_lookups
        policy_ladder_tier_step.catalog_score_lookups = timed_span(
            "score_lookups",
            original_step_lookups,
        )
        policy_ladder.catalog_score_lookups = timed_span(
            "score_lookups",
            original_ladder_lookups,
        )
        inference_api_payload.catalog_score_lookups = timed_span(
            "score_lookups",
            original_payload_lookups,
        )
        policy_ladder_tier_step.leftover_military_2x = timed_span(
            "leftover_lookup",
            original_step_leftover,
        )
        ship_first_family.leftover_military_2x = timed_span(
            "leftover_lookup",
            original_family_leftover,
        )
        ship_first_family.non_torp_military_2x = timed_span(
            "non_torp_lookup",
            original_non_torp,
        )
        completion_bindings = (
            (inference_row_runner, "run_policy_ladder_tier_step", "tier_step"),
            (inference_row_runner, "_outcome_after_ladder_complete", "ladder_complete"),
            (inference_row_runner, "finalize_policy_ladder_result", "finalize"),
            (inference_row_runner, "row_complete_from_ladder_finalize", "row_complete"),
            (policy_ladder_tier_step, "finish_tier_step", "finish_step"),
            (policy_ladder, "leftover_0_solutions", "leftover_0"),
            (policy_ladder, "worthwhile_remainder_bound_for_turn", "remainder_bound"),
            (row_complete_factory, "inference_result_to_api_payload", "api_payload"),
            (row_complete_factory, "row_complete_wire_payload_from_api_payload", "wire_from_api"),
            (analytic, "build_inference_solver_diagnostics", "solver_diagnostics"),
            (analytic, "catalog_to_actions_payload", "catalog_payload"),
            (inference_api_payload, "inference_api_payload", "wire_payload"),
            (inference_api_payload, "_serialize_solution_with_arithmetic", "serialize_solution"),
            (
                inference_api_payload,
                "solution_military_score_arithmetic_payload",
                "score_arithmetic",
            ),
        )
        completion_bindings = (
            *completion_bindings,
            (worthwhile_remainder_bound, "load_mine_stock_for_category", "mine_stock_load"),
            (
                worthwhile_remainder_bound,
                "compute_worthwhile_remainder_bound",
                "remainder_compute",
            ),
            (mine_stock, "load_mine_stock_asset", "mine_stock_asset"),
            (mine_stock, "parse_mine_stock_document", "histogram_parse"),
        )
        completion_patches: list[tuple[object, str, object]] = []
        for module, attr, name in completion_bindings:
            original = getattr(module, attr)
            setattr(module, attr, timed_span(name, original))
            completion_patches.append((module, attr, original))
        self._completion_patches = completion_patches
        self._solver_module = solver
        self._catalog_model = catalog_model
        self._original_build = original_build
        self._tier_step_module = policy_ladder_tier_step
        self._original_probe = original_probe
        self._original_solve_problem = original_solve_problem
        self._original_catalog = original_catalog
        self._original_merge = original_merge
        self._original_expand = original_expand
        self._family_module = ship_first_family
        self._ladder_module = policy_ladder
        self._payload_module = inference_api_payload
        self._original_step_leftover = original_step_leftover
        self._original_family_leftover = original_family_leftover
        self._original_non_torp = original_non_torp
        self._original_step_lookups = original_step_lookups
        self._original_ladder_lookups = original_ladder_lookups
        self._original_payload_lookups = original_payload_lookups
        self._original_build_problem = original_build_problem
        self._original_validate = original_validate
        self._original_collect = original_collect
        self._near_best_module = near_best
        self._original_read_combos = original_read_combos
        self._original_seed_cuts = original_seed_cuts
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        cp_model.CpSolver.solve = self._original_solve
        self._catalog_model.build_model = self._original_build
        self._tier_step_module.probe_degrade_aggregate_rewrites = self._original_probe
        self._tier_step_module.solve_inference_problem = self._original_solve_problem
        self._tier_step_module.build_action_catalog_from_turn = self._original_catalog
        self._catalog_model.merge_score_equivalent_combos = self._original_merge
        self._solver_module.expand_structural_hits_to_top_k = self._original_expand
        self._tier_step_module.leftover_military_2x = self._original_step_leftover
        self._family_module.leftover_military_2x = self._original_family_leftover
        self._family_module.non_torp_military_2x = self._original_non_torp
        self._tier_step_module.catalog_score_lookups = self._original_step_lookups
        self._ladder_module.catalog_score_lookups = self._original_ladder_lookups
        self._payload_module.catalog_score_lookups = self._original_payload_lookups
        self._tier_step_module.build_inference_problem = self._original_build_problem
        self._solver_module._validate_problem = self._original_validate
        self._solver_module.collect_near_best_structural_hits = self._original_collect
        self._near_best_module._read_combo_counts = self._original_read_combos
        self._near_best_module.seed_no_good_cuts_for_held_solutions = self._original_seed_cuts
        self._band_collector_type.on_solution_callback = self._original_on_solution
        for module, attr, original in self._completion_patches:
            setattr(module, attr, original)
        self._installed = False


def _solver_int(solver: cp_model.CpSolver, name: str) -> int:
    try:
        value = getattr(solver, name)
    except RuntimeError, AttributeError:
        return 0
    if callable(value):
        try:
            value = value()
        except RuntimeError, TypeError, ValueError:
            return 0
    try:
        return int(value)
    except TypeError, ValueError:
        return 0
