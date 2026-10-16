"""Reuse one tier's merged catalog and CP-SAT model across its catalog solves."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from api.analytics.military_score_inference import catalog_model
from api.analytics.military_score_inference import near_best_structural_search as near_best
from api.analytics.military_score_inference.catalog_model import (
    BuiltModel,
    CatalogMergePlan,
    ComboPins,
)
from api.analytics.military_score_inference.military_score_window import (
    BandMilitaryScoreWindow,
    ExactMilitaryScoreWindow,
    MilitaryScoreWindow,
    OvershootMilitaryScoreWindow,
)
from api.analytics.military_score_inference.models import InferenceProblem, InferenceSolution


class TierSolveCache:
    """Build each distinct model once, install held no-goods once, clone per solve.

    The clone is what search mutates. The cached model stays unsolved so the next
    pass with the same window, pin, and held solutions does not rebuild it.
    """

    def __init__(self, plan: CatalogMergePlan) -> None:
        self.plan = plan
        self._clean: dict[tuple[object, ...], BuiltModel] = {}
        self._seeded: dict[tuple[object, ...], tuple[BuiltModel, int, int]] = {}

    def fresh_model(
        self,
        problem: InferenceProblem,
        pins: ComboPins | None,
        seed_solutions: Sequence[InferenceSolution],
    ) -> tuple[BuiltModel, int, int]:
        """Return an unsolved clone plus the seed no-good counts baked into it."""
        clean_key = (
            _window_key(problem.military_score_window),
            ("open",) if pins is None else pins.cache_key(),
        )
        clean = self._clean.get(clean_key)
        if clean is None:
            merged = self.plan.catalog_for_pins(pins)
            clean = catalog_model.build_model(problem, merged)
            self._clean[clean_key] = clean

        held_key = tuple(solution.solution_id for solution in seed_solutions)
        seeded_key = clean_key + (held_key,)
        seeded = self._seeded.get(seeded_key)
        if seeded is None:
            seeded_model = catalog_model.clone_built_model(clean)
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
        return catalog_model.clone_built_model(model), applied, skipped


@dataclass(frozen=True)
class TierSolve:
    """Model cache and optional seed pins for one catalog solve."""

    cache: TierSolveCache
    pins: ComboPins | None = None


def _window_key(window: MilitaryScoreWindow) -> tuple[object, ...]:
    if isinstance(window, BandMilitaryScoreWindow):
        return ("band", window.alpha)
    if isinstance(window, OvershootMilitaryScoreWindow):
        return ("overshoot", window.cap_2x)
    if isinstance(window, ExactMilitaryScoreWindow):
        return ("exact",)
    return ("exact",)
