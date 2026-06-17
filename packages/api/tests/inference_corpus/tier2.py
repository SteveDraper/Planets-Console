"""Tier 2 ship-level ground truth compatibility against multi-perspective inventory."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from api.models.game import TurnInfo
from api.models.player import Score

from tests.inference_corpus.complexity import merge_turn_inventories
from tests.inference_corpus.ground_truth import GroundTruth, extract_ground_truth_v1
from tests.inference_corpus.models import ComplexityLevel


def verify_tier2_compatibility(
    *,
    ground_truth: GroundTruth,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    complexity: ComplexityLevel,
    other_prior_turns: tuple[TurnInfo, ...] = (),
    other_score_turns: tuple[TurnInfo, ...] = (),
) -> str | None:
    """Return an error when ground truth contradicts merged multi-perspective inventory."""
    if not ground_truth:
        return None

    merged_prior, merged_score = _merged_turn_snapshots(
        prior_turn=prior_turn,
        score_turn=score_turn,
        other_prior_turns=other_prior_turns,
        other_score_turns=other_score_turns,
    )
    merged_extraction = extract_ground_truth_v1(
        prior_turn=merged_prior,
        score_turn=merged_score,
        player_id=player_id,
        score=score,
        complexity=complexity,
    )
    if not merged_extraction.available:
        return (
            "tier2: multi-perspective inventory could not be reconciled with ground truth "
            f"({merged_extraction.unavailable_reason})"
        )

    return compare_ground_truth_to_merged_inventory(
        ground_truth,
        merged_extraction.ground_truth,
    )


def compare_ground_truth_to_merged_inventory(
    ground_truth: GroundTruth,
    merged_ground_truth: GroundTruth,
) -> str | None:
    """Fail when primary ground truth claims more activity than merged inventory supports."""
    primary = Counter()
    merged = Counter()
    for action_id, count in ground_truth:
        primary[action_id] += count
    for action_id, count in merged_ground_truth:
        merged[action_id] += count
    for action_id, count in sorted(primary.items()):
        merged_count = merged[action_id]
        if merged_count < count:
            return (
                f"tier2: ground truth {action_id} count {count} "
                f"exceeds multi-perspective inventory {merged_count}"
            )
    return None


def _merged_turn_snapshots(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    other_prior_turns: tuple[TurnInfo, ...],
    other_score_turns: tuple[TurnInfo, ...],
) -> tuple[TurnInfo, TurnInfo]:
    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=other_prior_turns,
        other_score_turns=other_score_turns,
    )
    return (
        replace(prior_turn, ships=merged.prior_ships),
        replace(score_turn, ships=merged.score_ships),
    )
