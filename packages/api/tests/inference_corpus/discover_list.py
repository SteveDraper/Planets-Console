"""Human-readable discovery listings with ground truth summaries."""

from dataclasses import dataclass

from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.complexity import classify_complexity
from tests.inference_corpus.discovery import discover_cases_for_game
from tests.inference_corpus.ground_truth import (
    describe_inventory_activity,
    extract_ground_truth_v1,
    format_ground_truth_summary,
)
from tests.inference_corpus.models import ComplexityLevel, DiscoveredCase
from tests.inference_corpus.run import merged_inventory_for_case, score_for_player


@dataclass(frozen=True)
class DiscoveredCaseListing:
    case: DiscoveredCase
    player_id: int
    player_name: str | None
    complexity: ComplexityLevel
    complexity_reasons: tuple[str, ...]
    ground_truth_available: bool
    summary: str


def discover_case_listings(
    *,
    store: StoreService,
    turn_load: TurnLoadService,
    game_service: GameService,
    game_id: int,
    min_host_turn: int | None = None,
    max_host_turn: int | None = None,
    game_info: GameInfo | None = None,
) -> list[DiscoveredCaseListing]:
    """Discover cases in a host-turn range and attach ground-truth summaries."""
    cases = discover_cases_for_game(
        store,
        game_id,
        min_host_turn=min_host_turn,
        max_host_turn=max_host_turn,
    )
    info = game_info or game_service.get_game_info(game_id)
    listings: list[DiscoveredCaseListing] = []
    for case in cases:
        listings.append(
            _listing_for_case(
                case,
                store=store,
                turn_load=turn_load,
                game_info=info,
            )
        )
    return listings


def format_listing_line(listing: DiscoveredCaseListing) -> str:
    player_label = listing.player_name or f"player {listing.player_id}"
    return (
        f"host turn {listing.case.host_turn}, perspective {listing.case.perspective} "
        f"({player_label}): {listing.summary} [{listing.complexity}]"
    )


def format_listing_report(listings: list[DiscoveredCaseListing], *, game_id: int) -> list[str]:
    if not listings:
        return [f"game {game_id}: no cases discovered in range"]

    lines = [f"game {game_id}: {len(listings)} case(s)"]
    current_host_turn: int | None = None
    for listing in listings:
        if listing.case.host_turn != current_host_turn:
            current_host_turn = listing.case.host_turn
            lines.append(f"  host turn {current_host_turn}:")
        player_label = listing.player_name or f"player {listing.player_id}"
        lines.append(
            f"    perspective {listing.case.perspective} ({player_label}): {listing.summary}"
        )
    return lines


def _listing_for_case(
    case: DiscoveredCase,
    *,
    store: StoreService,
    turn_load: TurnLoadService,
    game_info: GameInfo,
) -> DiscoveredCaseListing:
    score_turn_number = case.host_turn + 1
    prior_turn = turn_load.get_turn_info(case.game_id, case.perspective, case.host_turn)
    score_turn = turn_load.get_turn_info(case.game_id, case.perspective, score_turn_number)
    player_id = GameService.player_id_for_perspective(game_info, case.perspective, case.game_id)
    player_name = _player_name(game_info, case.perspective)
    score = score_for_player(score_turn.scores, player_id, case.id)

    merged = merged_inventory_for_case(
        case,
        turn_load=turn_load,
        store=store,
        prior_turn=prior_turn,
        score_turn=score_turn,
    )
    complexity, complexity_reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )

    extraction = extract_ground_truth_v1(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity=complexity,
    )
    if extraction.available:
        summary = format_ground_truth_summary(extraction.ground_truth, score_turn=score_turn)
    else:
        summary = describe_inventory_activity(
            prior_turn=prior_turn,
            score_turn=score_turn,
            player_id=player_id,
        )

    return DiscoveredCaseListing(
        case=case,
        player_id=player_id,
        player_name=player_name,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        ground_truth_available=extraction.available,
        summary=summary,
    )


def _player_name(game_info: GameInfo, perspective: int) -> str | None:
    if perspective < 1 or perspective > len(game_info.players):
        return None
    username = game_info.players[perspective - 1].username.strip()
    return username or None
