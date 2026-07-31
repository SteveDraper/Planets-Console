#!/usr/bin/env python3
"""Probe homeworld layout-prior costs for a stored shell scope.

Loads game state from file storage, materializes the homeworld candidate view
(same promote/cull/layout-prior path as map/table), then scores the preferred
selection and optional planet swaps without changing other choices.

Examples::

    uv run python scripts/probe_layout_prior_cost.py \\
        --game-id 680224 --perspective 2 --turn 14

    uv run python scripts/probe_layout_prior_cost.py \\
        --game-id 680224 --race-id 2 --turn 14 \\
        --swap-from 29 --swap-to 23
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
_api_root_str = str(_API_ROOT)
if _api_root_str in sys.path:
    sys.path.remove(_api_root_str)
sys.path.insert(0, _api_root_str)

import typer  # noqa: E402
from api.analytics.compute_context import make_analytic_compute_context  # noqa: E402
from api.analytics.homeworld_locator.baseline_ensure import (  # noqa: E402
    materialize_homeworld_candidate_view,
)
from api.analytics.homeworld_locator.compute_services import (  # noqa: E402
    build_ephemeral_homeworld_services,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID  # noqa: E402
from api.analytics.homeworld_locator.layout_prior import (  # noqa: E402
    try_layout_prior_problem,
)
from api.analytics.homeworld_locator.layout_prior_anneal import (  # noqa: E402
    AnnealingLayoutPriorSolver,
)
from api.analytics.homeworld_locator.layout_prior_cost import (  # noqa: E402
    LayoutPriorCostBreakdown,
    evaluate_layout_prior_selection_breakdown,
)
from api.analytics.homeworld_locator.layout_prior_problem import (  # noqa: E402
    LayoutPriorProblem,
)
from api.analytics.homeworld_locator.layout_prior_solver import LayoutPriorSolution  # noqa: E402
from api.analytics.homeworld_locator.layout_prior_stop_gate import (  # noqa: E402
    DeadlineStopGate,
)
from api.analytics.homeworld_locator.models import OriginDistanceObservation  # noqa: E402
from api.analytics.homeworld_locator.persistence import (  # noqa: E402
    HomeworldLocatorPersistenceService,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateView  # noqa: E402
from api.analytics.military_score_inference.prior_mining.storage_bootstrap import (  # noqa: E402
    make_mining_services_for_storage_root,
)
from api.errors import NotFoundError, ValidationError  # noqa: E402
from api.models.game import TurnInfo  # noqa: E402
from api.models.planet import Planet  # noqa: E402
from api.services.game_service import GameService  # noqa: E402

app = typer.Typer(add_completion=False, help=__doc__)


@dataclass(frozen=True)
class ScoredSelection:
    """One scored discrete assignment (with stand-in positions used for scoring)."""

    label: str
    chosen_by_sector: dict[int, int]
    stand_in_positions: Mapping[int, tuple[float, float]]
    cost: float
    tie_key: tuple[tuple[int, int], ...]
    breakdown: LayoutPriorCostBreakdown


def _resolve_perspective(
    game_service: GameService,
    *,
    game_id: int,
    perspective: int | None,
    race_id: int | None,
) -> int:
    if perspective is not None and race_id is not None:
        raise ValidationError("pass only one of --perspective and --race-id")
    if perspective is not None:
        return perspective
    if race_id is None:
        raise ValidationError("provide --perspective or --race-id")
    info = game_service.get_game_info(game_id)
    if info is None:
        raise NotFoundError(f"game info not found for game {game_id}")
    matches = [player for player in info.players if int(player.raceid) == int(race_id)]
    if not matches:
        raise NotFoundError(f"no player with raceid={race_id} in game {game_id}")
    if len(matches) > 1:
        ids = ", ".join(str(player.id) for player in matches)
        raise ValidationError(f"multiple players with raceid={race_id}: ids {ids}")
    return GameService.perspective_for_player_id(info, matches[0].id, game_id)


def _build_problem(
    *,
    turn: TurnInfo,
    view: HomeworldCandidateView,
    origin_distance_observations: Sequence[OriginDistanceObservation] = (),
) -> LayoutPriorProblem:
    problem = try_layout_prior_problem(
        view.candidates,
        turn=turn,
        view=view,
        origin_distance_observations=origin_distance_observations,
    )
    if problem is None:
        raise ValidationError(
            "layout prior emission gate failed (no pin, ineligible map, or no category)"
        )
    return problem


def _format_planet(planet: Planet | None, planet_id: int) -> str:
    if planet is None:
        return f"p{planet_id} (missing)"
    return f"p{planet_id} @ ({planet.x}, {planet.y})"


def _print_sector_map(
    problem: LayoutPriorProblem,
    chosen: Mapping[int, int],
    *,
    stand_ins: Mapping[int, tuple[float, float]],
) -> None:
    typer.echo("Sector map:")
    for state in problem.sector_states:
        if state.kind == "fixed":
            typer.echo(
                f"  sector {state.sector_index}: fixed "
                f"p{state.fixed_planet_id} "
                f"{'slot-anchored' if state.is_slot_anchored else 'orphan-definite'}"
            )
        elif state.kind == "choice":
            chosen_id = chosen.get(state.sector_index)
            options = ", ".join(f"p{pid}" for pid in state.choice_planet_ids)
            typer.echo(f"  sector {state.sector_index}: choice p{chosen_id} (legal: {options})")
        elif state.kind == "stand_in":
            pos = stand_ins.get(state.sector_index) or state.stand_in_position
            typer.echo(f"  sector {state.sector_index}: stand-in {pos}")
        else:
            typer.echo(f"  sector {state.sector_index}: skip")


def _swap_choice(
    chosen: Mapping[int, int],
    problem: LayoutPriorProblem,
    *,
    remove_planet_id: int,
    add_planet_id: int,
) -> dict[int, int]:
    if remove_planet_id == add_planet_id:
        raise ValidationError("--swap planets must differ")
    sector_for_remove = next(
        (sector for sector, planet_id in chosen.items() if planet_id == remove_planet_id),
        None,
    )
    if sector_for_remove is None:
        raise ValidationError(
            f"planet {remove_planet_id} is not in the preferred choice set: "
            f"{sorted(chosen.values())}"
        )
    if add_planet_id in chosen.values():
        raise ValidationError(f"planet {add_planet_id} is already selected in another sector")
    choice_state = next(
        state
        for state in problem.sector_states
        if state.sector_index == sector_for_remove and state.kind == "choice"
    )
    if add_planet_id not in choice_state.choice_planet_ids:
        raise ValidationError(
            f"planet {add_planet_id} is not a legal possible in sector "
            f"{sector_for_remove}; legal={list(choice_state.choice_planet_ids)}"
        )
    updated = dict(chosen)
    updated[sector_for_remove] = add_planet_id
    return updated


def _score(
    label: str,
    problem: LayoutPriorProblem,
    chosen: Mapping[int, int],
    stand_ins: Mapping[int, tuple[float, float]],
) -> ScoredSelection:
    scored = evaluate_layout_prior_selection_breakdown(
        problem, chosen, stand_in_positions=stand_ins
    )
    if scored is None:
        raise ValidationError(f"could not assemble positions for {label!r}")
    breakdown, tie_key = scored
    return ScoredSelection(
        label=label,
        chosen_by_sector=dict(chosen),
        stand_in_positions=stand_ins,
        cost=breakdown.total,
        tie_key=tie_key,
        breakdown=breakdown,
    )


def _sector_label(
    sector: int,
    chosen: Mapping[int, int],
    problem: LayoutPriorProblem,
) -> str:
    if sector in chosen:
        return f"sector {sector} (p{chosen[sector]})"
    state = next(s for s in problem.sector_states if s.sector_index == sector)
    if state.kind == "fixed":
        return f"sector {sector} (fixed p{state.fixed_planet_id})"
    if state.kind == "stand_in":
        return f"sector {sector} (stand-in)"
    return f"sector {sector} ({state.kind})"


def _print_focus_planet_terms(
    selection: ScoredSelection,
    *,
    planet_id: int,
    problem: LayoutPriorProblem,
) -> None:
    sector = next(
        (s for s, pid in selection.chosen_by_sector.items() if pid == planet_id),
        None,
    )
    if sector is None:
        typer.echo(f"  (p{planet_id} not in this selection)")
        return
    bd = selection.breakdown
    typer.echo(f"  focus p{planet_id} in sector {sector}:")
    center_term = next((t for t in bd.center_terms if t.sector_index == sector), None)
    if center_term is None:
        typer.echo("    center-distance: omitted (slot-anchored)")
    else:
        typer.echo(
            f"    center-distance: {center_term.center_distance_ly:.3f} LY "
            f"→ -log dens={center_term.neg_log_density:.4f}"
        )
    incoming = next((e for e in bd.neighbor_edges if e.to_sector == sector), None)
    outgoing = next((e for e in bd.neighbor_edges if e.from_sector == sector), None)
    for label, edge in (("prev→focus", incoming), ("focus→next", outgoing)):
        if edge is None:
            typer.echo(f"    {label}: (missing)")
            continue
        typer.echo(
            f"    {label}: {_sector_label(edge.from_sector, selection.chosen_by_sector, problem)}"
            f" → {_sector_label(edge.to_sector, selection.chosen_by_sector, problem)}: "
            f"{edge.separation_ly:.3f} LY → -log dens={edge.neg_log_density:.4f}"
        )


def _print_scored(
    selection: ScoredSelection,
    planets_by_id: Mapping[int, Planet],
    *,
    problem: LayoutPriorProblem,
    focus_planet_ids: Sequence[int] = (),
) -> None:
    typer.echo(f"\n{selection.label}")
    bd = selection.breakdown
    typer.echo(
        f"  cost: {selection.cost:.6f} "
        f"(neighbor_mean={bd.neighbor_mean:.6f} + center_mean={bd.center_mean:.6f}"
        f" + evidence_mean={bd.evidence_mean:.6f})"
    )
    typer.echo(f"  tie_key: {selection.tie_key}")
    ordered = sorted(selection.chosen_by_sector.items())
    planets = ", ".join(
        _format_planet(planets_by_id.get(planet_id), planet_id) for _, planet_id in ordered
    )
    typer.echo(f"  choices: {planets}")
    for planet_id in focus_planet_ids:
        _print_focus_planet_terms(selection, planet_id=planet_id, problem=problem)


@app.command()
def main(
    game_id: int = typer.Option(..., "--game-id", help="Game id under storage_root."),
    turn: int = typer.Option(..., "--turn", help="Shell turn number."),
    perspective: int | None = typer.Option(
        None, "--perspective", help="Perspective slot (1-based). Mutually exclusive with --race-id."
    ),
    race_id: int | None = typer.Option(
        None,
        "--race-id",
        help=(
            "Resolve perspective from GameInfo raceid (e.g. 2=Lizard). "
            "Mutually exclusive with --perspective."
        ),
    ),
    storage_root: Path = typer.Option(
        Path("./.data"),
        "--storage-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="File storage root (default ./.data).",
    ),
    budget_ms: int = typer.Option(
        500,
        "--budget-ms",
        help="Wall-clock SA budget when recomputing the preferred selection.",
    ),
    swap_from: int | None = typer.Option(
        None,
        "--swap-from",
        help="Planet id to remove from the preferred choice set (use with --swap-to).",
    ),
    swap_to: int | None = typer.Option(
        None,
        "--swap-to",
        help="Planet id to insert in the same sector (use with --swap-from).",
    ),
) -> None:
    """Print preferred layout-prior cost and optional single-planet swap cost."""
    if (swap_from is None) ^ (swap_to is None):
        raise typer.BadParameter("provide both --swap-from and --swap-to, or neither")

    storage, turn_load, game_service = make_mining_services_for_storage_root(storage_root)
    resolved_perspective = _resolve_perspective(
        game_service,
        game_id=game_id,
        perspective=perspective,
        race_id=race_id,
    )
    shell_turn = turn_load.get_turn_info(game_id, resolved_perspective, turn)
    game_info = game_service.get_game_info(game_id)
    persistence = HomeworldLocatorPersistenceService(storage)
    services = build_ephemeral_homeworld_services(
        persistence=persistence,
        game_id=game_id,
        perspective=resolved_perspective,
        load_turn=lambda n: turn_load.get_turn_info(game_id, resolved_perspective, n),
        list_stored_turns=lambda: turn_load.list_stored_turn_numbers(game_id, resolved_perspective),
        game_info=game_info,
    )
    ctx = make_analytic_compute_context(
        shell_turn,
        load_turn=lambda n: turn_load.get_turn_info(game_id, resolved_perspective, n),
        export_services={ANALYTIC_ID: services},
    ).exports
    view = materialize_homeworld_candidate_view(ctx, shell_turn=shell_turn)
    if not view.available:
        raise ValidationError(f"homeworld locator unavailable: {view.inactive_reason}")

    aggregate = persistence.get_evidence_aggregate(game_id, resolved_perspective, turn)
    observations = () if aggregate is None else aggregate.origin_distance_observations
    problem = _build_problem(
        turn=shell_turn,
        view=view,
        origin_distance_observations=observations,
    )
    solver = AnnealingLayoutPriorSolver()
    solve_result = solver.solve(problem, stop_gate=DeadlineStopGate(budget_ms))
    solution: LayoutPriorSolution = solve_result.solution

    preferred = _score(
        "preferred (anneal + sample-grid refine)",
        problem,
        solution.chosen_planet_ids_by_sector,
        solution.stand_in_positions_by_sector,
    )

    typer.echo(
        f"game={game_id} perspective={resolved_perspective} turn={turn} budget_ms={budget_ms}"
    )
    typer.echo(
        f"viewpoint player id={shell_turn.player.id} "
        f"username={getattr(shell_turn.player, 'username', None)}"
    )
    _print_sector_map(
        problem,
        preferred.chosen_by_sector,
        stand_ins=preferred.stand_in_positions,
    )
    planets_by_id = problem.planets_by_id
    focus_ids: list[int] = []
    if swap_from is not None and swap_to is not None:
        focus_ids = [swap_from, swap_to]
    _print_scored(preferred, planets_by_id, problem=problem, focus_planet_ids=focus_ids)

    wire_most_probable = sorted(row.planet_id for row in view.candidates if row.is_most_probable)
    solver_ids = sorted(preferred.chosen_by_sector.values())
    if wire_most_probable and wire_most_probable != solver_ids:
        typer.echo(
            "\nnote: persisted/wire mostProbablePlanetIds "
            f"{wire_most_probable} differ from this probe's anneal result "
            f"{solver_ids} (recompute under --budget-ms {budget_ms})."
        )

    if swap_from is not None and swap_to is not None:
        swapped_chosen = _swap_choice(
            preferred.chosen_by_sector,
            problem,
            remove_planet_id=swap_from,
            add_planet_id=swap_to,
        )
        remove_id, add_id = swap_from, swap_to
        # Keep preferred stand-ins fixed so the delta isolates the discrete swap.
        swapped = _score(
            f"swap p{remove_id} -> p{add_id} (stand-ins held)",
            problem,
            swapped_chosen,
            preferred.stand_in_positions,
        )
        _print_scored(
            swapped,
            planets_by_id,
            problem=problem,
            focus_planet_ids=[remove_id, add_id],
        )
        delta = swapped.cost - preferred.cost
        typer.echo(f"\ndelta (swap - preferred): {delta:+.6f}")
        typer.echo(
            "note: total cost is mean(-log Normal dens) over all ring edges plus "
            "mean(-log Normal dens) over all unpinned center distances plus "
            "λ-blended soft origin-distance evidence; focus lines "
            "show per-term -log densities, not how much the means move."
        )


if __name__ == "__main__":
    app()
