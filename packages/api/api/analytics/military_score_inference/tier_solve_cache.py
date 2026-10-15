"""Reuse one tier's merged catalog and CP-SAT model across its catalog solves."""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.military_score_inference.military_score_window import (
    BandMilitaryScoreWindow,
    ExactMilitaryScoreWindow,
    MilitaryScoreWindow,
    OvershootMilitaryScoreWindow,
)
from api.analytics.military_score_inference.models import InferenceProblem, InferenceSolution
from api.analytics.military_score_inference.solver import CatalogMergePlan, _BuiltModel


class TierSolveCache:
    """Build each distinct model once, install held no-goods once, clone per solve.

    The clone is what search mutates. The cached model stays unsolved so the next
    pass with the same window, pin, and held solutions does not rebuild it.
    """

    def __init__(self, plan: CatalogMergePlan) -> None:
        self.plan = plan
        self._clean: dict[tuple[object, ...], _BuiltModel] = {}
        self._seeded: dict[tuple[object, ...], tuple[_BuiltModel, int, int]] = {}

    def fresh_model(
        self,
        problem: InferenceProblem,
        fixed_combo_counts: dict[str, int] | None,
        combo_count_neighborhood: int,
        seed_solutions: Sequence[InferenceSolution],
    ) -> tuple[_BuiltModel, int, int]:
        """Return an unsolved clone plus the seed no-good counts baked into it."""
        from api.analytics.military_score_inference import near_best_structural_search as near_best
        from api.analytics.military_score_inference import solver as solver_module

        clean_key = (
            _window_key(problem.military_score_window),
            _pins_key(fixed_combo_counts, combo_count_neighborhood),
        )
        clean = self._clean.get(clean_key)
        if clean is None:
            merged = self.plan.catalog_for_pins(fixed_combo_counts, combo_count_neighborhood)
            clean = solver_module._build_model(problem, merged)
            self._clean[clean_key] = clean

        held_key = tuple(id(solution) for solution in seed_solutions)
        seeded_key = clean_key + (held_key,)
        seeded = self._seeded.get(seeded_key)
        if seeded is None:
            seeded_model = solver_module.clone_built_model(clean)
            if seed_solutions:
                applied, skipped = near_best.seed_no_good_cuts_for_held_solutions(
                    seeded_model.model,
                    problem=problem,
                    merged_combo_catalog=seeded_model.merged_combo_catalog,
                    action_count_vars=seeded_model.action_count_vars,
                    combo_count_vars=seeded_model.combo_count_vars,
                    seed_solutions=seed_solutions,
                )
            else:
                applied, skipped = 0, 0
            seeded = (seeded_model, applied, skipped)
            self._seeded[seeded_key] = seeded

        model, applied, skipped = seeded
        return solver_module.clone_built_model(model), applied, skipped


def _window_key(window: MilitaryScoreWindow) -> tuple[object, ...]:
    if isinstance(window, BandMilitaryScoreWindow):
        return ("band", window.alpha)
    if isinstance(window, OvershootMilitaryScoreWindow):
        return ("overshoot", window.cap_2x)
    if isinstance(window, ExactMilitaryScoreWindow):
        return ("exact",)
    return ("exact",)


def _pins_key(
    fixed_combo_counts: dict[str, int] | None,
    neighborhood: int,
) -> tuple[object, ...]:
    if not fixed_combo_counts:
        return ("open",)
    return ("pin", neighborhood, tuple(sorted(fixed_combo_counts.items())))
