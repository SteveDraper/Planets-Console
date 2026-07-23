"""Signature-deduped top-K buffer for inference solutions ranked by objective."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable

from api.analytics.military_score_inference.models import InferenceSolution

SolutionSignature = tuple[tuple[str, int], ...]

__all__ = (
    "SolutionSignature",
    "admit_ranked_solution",
    "admit_ranked_solutions",
    "solution_signature",
)


def solution_signature(solution: InferenceSolution) -> SolutionSignature:
    action_counts = ((action.action_id, action.count) for action in solution.actions)
    combo_counts = ((build.combo_id, build.count) for build in solution.ship_builds)
    return tuple(sorted(action_counts) + sorted(combo_counts))


def admit_ranked_solution(
    solutions: list[InferenceSolution],
    seen_signatures: set[SolutionSignature],
    candidate: InferenceSolution,
    *,
    max_solutions: int,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> bool:
    """Admit ``candidate`` into a signature-deduped top-K (objective descending).

    Mutates ``solutions`` and ``seen_signatures`` in place. Returns True when the
    candidate enters the buffer (including when it replaces a worse held row).
    """
    if max_solutions <= 0:
        return False
    signature = solution_signature(candidate)
    if signature in seen_signatures:
        return False
    if len(solutions) >= max_solutions:
        worst = solutions[-1]
        if candidate.objective_value <= worst.objective_value:
            return False
        seen_signatures.remove(solution_signature(worst))
        solutions.pop()
    seen_signatures.add(signature)
    objectives = [-held.objective_value for held in solutions]
    index = bisect_right(objectives, -candidate.objective_value)
    solutions.insert(index, candidate)
    if on_admitted is not None:
        on_admitted(candidate)
    return True


def admit_ranked_solutions(
    solutions: list[InferenceSolution],
    seen_signatures: set[SolutionSignature],
    candidates: Iterable[InferenceSolution],
    *,
    max_solutions: int,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> int:
    """Admit each candidate via :func:`admit_ranked_solution`; return admit count."""
    admitted = 0
    for candidate in candidates:
        if admit_ranked_solution(
            solutions,
            seen_signatures,
            candidate,
            max_solutions=max_solutions,
            on_admitted=on_admitted,
        ):
            admitted += 1
    return admitted
