"""Core scoreboard analytic."""

from collections.abc import Callable, Iterator, Mapping

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    iter_scores_table_inference_events,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.scores.compute_orchestration import (
    SCORES_COMPUTE_PROFILE,
    SCORES_MATERIALIZE,
    SCORES_PERSISTENCE_POLICY,
    SCORES_SCOPE_KEY_SPEC,
    SCORES_TIER_SOLVE,
    build_scores_materialize_job_wire,
    build_scores_tier_solve_job_wire,
    run_scores_materialize,
    run_scores_tier_solve,
)
from api.analytics.scores.inference import get_scores_row_inference as get_scores_row_inference
from api.analytics.scores_assets import ANALYTIC_ID
from api.analytics.turn_roster import players_by_id as turn_players_by_id
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


def _score_row(
    score,
    *,
    players_by_id: dict[int, object],
    races_by_id: dict[int, object],
) -> dict[str, object]:
    player = players_by_id.get(score.ownerid)
    race = races_by_id.get(player.raceid) if player is not None else None
    if race is not None and player is not None:
        race_player = f"{race.name} ({player.username})"
    elif player is not None:
        race_player = player.username
    else:
        race_player = f"Player {score.ownerid}"
    return {
        "playerId": score.ownerid,
        "racePlayer": race_player,
        "planets": {"value": score.planets, "change": score.planetchange},
        "starbases": {"value": score.starbases, "change": score.starbasechange},
        "warShips": {"value": score.capitalships, "change": score.shipchange},
        "freighters": {"value": score.freighters, "change": score.freighterchange},
        "military": {
            "value": score.militaryscore,
            "change": score.militarychange,
        },
        "priorityPoints": {
            "value": score.prioritypoints,
            "change": score.prioritypointchange,
        },
    }


def compute_scores_table(ctx: AnalyticComputeContext) -> dict:
    """Return scoreboard values for each player in a turn."""
    turn = ctx.turn
    players_by_id = turn_players_by_id(turn)
    races_by_id = {race.id: race for race in turn.races}

    rows = [
        _score_row(score, players_by_id=players_by_id, races_by_id=races_by_id)
        for score in turn.scores
    ]
    return {"analyticId": ANALYTIC_ID, "rows": rows}


def get_scores_table(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(compute_scores_table, turn, options)


def iter_scores_table_inference_stream(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    reload_host_turn: Callable[[], TurnInfo] | None = None,
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None,
    resolve_fleet_torp_resolution_for_player: Callable[[int], PriorTurnFleetTorpResolution]
    | None = None,
    export_services: Mapping[str, object] | None = None,
    persistence: InferenceRowPersistenceService | None = None,
    scheduler: InferenceRowScheduler | None = None,
) -> Iterator[dict[str, object]]:
    """Yield NDJSON wire events for all scoreboard rows on one stream."""
    yield from iter_scores_table_inference_events(
        turn,
        player_ids,
        game_id=game_id,
        perspective=perspective,
        load_scoreboard_turn=load_scoreboard_turn,
        reload_host_turn=reload_host_turn,
        resolve_mask_for_player=resolve_mask_for_player,
        resolve_fleet_torp_resolution_for_player=resolve_fleet_torp_resolution_for_player,
        export_services=export_services,
        persistence=persistence,
        scheduler=scheduler,
    )


def _load_scores_export_catalog():
    from api.analytics.scores.exports import EXPORT_CATALOG

    return EXPORT_CATALOG


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_scores_table,
    export_catalog_loader=_load_scores_export_catalog,
    scope_key_spec=SCORES_SCOPE_KEY_SPEC,
    compute_profile=SCORES_COMPUTE_PROFILE,
    persistence_policy=SCORES_PERSISTENCE_POLICY,
    build_step_job_wires=(
        (SCORES_MATERIALIZE, build_scores_materialize_job_wire),
        (SCORES_TIER_SOLVE, build_scores_tier_solve_job_wire),
    ),
    run_steps=(
        (SCORES_MATERIALIZE, run_scores_materialize),
        (SCORES_TIER_SOLVE, run_scores_tier_solve),
    ),
)
