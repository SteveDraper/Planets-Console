"""Re-export Core complexity classification for the inference corpus harness."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_corpus_complexity import (
    COMPLEXITY_ORDINAL,
    ComplexityLevel,
    MergedTurnInventory,
    classify_complexity,
    merge_turn_inventories,
    parse_max_complexity,
)
from api.models.game import TurnInfo
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.discovery import list_perspectives_with_turn_pair
from tests.inference_corpus.models import DiscoveredCase

__all__ = [
    "COMPLEXITY_ORDINAL",
    "ComplexityLevel",
    "DiscoveredCase",
    "MergedTurnInventory",
    "classify_complexity",
    "merge_turn_inventories",
    "merged_inventory_for_case",
    "parse_max_complexity",
]


def merged_inventory_for_case(
    case: DiscoveredCase,
    *,
    turn_load: TurnLoadService,
    store: StoreService,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
) -> MergedTurnInventory:
    score_turn_number = case.host_turn + 1
    other_perspectives = [
        perspective
        for perspective in list_perspectives_with_turn_pair(
            store,
            game_id=case.game_id,
            host_turn=case.host_turn,
            score_turn=score_turn_number,
        )
        if perspective != case.perspective
    ]
    other_prior: list[TurnInfo] = []
    other_score: list[TurnInfo] = []
    for perspective in other_perspectives:
        other_prior.append(turn_load.get_turn_info(case.game_id, perspective, case.host_turn))
        other_score.append(turn_load.get_turn_info(case.game_id, perspective, score_turn_number))
    return merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=tuple(other_prior),
        other_score_turns=tuple(other_score),
    )
