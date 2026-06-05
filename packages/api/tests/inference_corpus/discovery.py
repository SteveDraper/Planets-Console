"""Discover inference corpus cases from stored game turn pairs."""

from api.errors import NotFoundError
from api.services.store_service import StoreService

from tests.inference_corpus.models import DiscoveredCase


def discovered_case_id(*, game_id: int, perspective: int, host_turn: int) -> str:
    return f"{game_id}-p{perspective}-host{host_turn}"


def discover_cases_for_game(
    store: StoreService,
    game_id: int,
    *,
    min_host_turn: int | None = None,
    max_host_turn: int | None = None,
) -> list[DiscoveredCase]:
    """Emit one case per consecutive stored turn pair (N, N+1) for each perspective."""
    cases: list[DiscoveredCase] = []
    try:
        game_shallow = store.read_shallow(f"games/{game_id}")
    except NotFoundError:
        return []

    for perspective_segment in game_shallow["children"]:
        if not perspective_segment.isdigit():
            continue
        perspective = int(perspective_segment)
        if perspective < 1:
            continue
        cases.extend(
            _discover_cases_for_perspective(
                store,
                game_id=game_id,
                perspective=perspective,
                min_host_turn=min_host_turn,
                max_host_turn=max_host_turn,
            )
        )
    return sorted(cases, key=lambda case: (case.perspective, case.host_turn))


def discover_cases(
    store: StoreService,
    *,
    game_id: int | None = None,
    min_host_turn: int | None = None,
    max_host_turn: int | None = None,
) -> list[DiscoveredCase]:
    """Discover cases for one game or every game id under ``games/``."""
    if game_id is not None:
        return discover_cases_for_game(
            store,
            game_id,
            min_host_turn=min_host_turn,
            max_host_turn=max_host_turn,
        )

    try:
        games_shallow = store.read_shallow("games")
    except NotFoundError:
        return []

    cases: list[DiscoveredCase] = []
    for game_segment in games_shallow["children"]:
        try:
            discovered_game_id = int(game_segment)
        except ValueError:
            continue
        cases.extend(
            discover_cases_for_game(
                store,
                discovered_game_id,
                min_host_turn=min_host_turn,
                max_host_turn=max_host_turn,
            )
        )
    return sorted(cases, key=lambda case: (case.game_id, case.perspective, case.host_turn))


def list_perspectives_with_turn_pair(
    store: StoreService,
    *,
    game_id: int,
    host_turn: int,
    score_turn: int,
) -> list[int]:
    """Return sorted perspective slots that have both host and score turns stored."""
    try:
        game_shallow = store.read_shallow(f"games/{game_id}")
    except NotFoundError:
        return []

    perspectives: list[int] = []
    for perspective_segment in game_shallow["children"]:
        if not perspective_segment.isdigit():
            continue
        perspective = int(perspective_segment)
        if perspective < 1:
            continue
        if _has_turn(store, game_id, perspective, host_turn) and _has_turn(
            store, game_id, perspective, score_turn
        ):
            perspectives.append(perspective)
    return sorted(perspectives)


def _discover_cases_for_perspective(
    store: StoreService,
    *,
    game_id: int,
    perspective: int,
    min_host_turn: int | None = None,
    max_host_turn: int | None = None,
) -> list[DiscoveredCase]:
    turns_path = f"games/{game_id}/{perspective}/turns"
    try:
        turns_shallow = store.read_shallow(turns_path)
    except NotFoundError:
        return []

    turn_numbers = sorted(
        int(segment) for segment in turns_shallow["children"] if segment.isdigit()
    )
    cases: list[DiscoveredCase] = []
    for index in range(len(turn_numbers) - 1):
        host_turn = turn_numbers[index]
        score_turn = turn_numbers[index + 1]
        if score_turn != host_turn + 1:
            continue
        if min_host_turn is not None and host_turn < min_host_turn:
            continue
        if max_host_turn is not None and host_turn > max_host_turn:
            continue
        cases.append(
            DiscoveredCase(
                id=discovered_case_id(
                    game_id=game_id,
                    perspective=perspective,
                    host_turn=host_turn,
                ),
                game_id=game_id,
                perspective=perspective,
                host_turn=host_turn,
            )
        )
    return cases


def _has_turn(store: StoreService, game_id: int, perspective: int, turn_number: int) -> bool:
    try:
        store.read_shallow(f"games/{game_id}/{perspective}/turns/{turn_number}")
        return True
    except NotFoundError:
        return False
