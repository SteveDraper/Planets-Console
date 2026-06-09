"""Per-row stream orchestration for policy-ladder and accelerated inference paths."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_accelerated import (
    AcceleratedSegmentSolve,
    AcceleratedStreamRowComplete,
    build_accelerated_backfill_stream_row_complete,
    build_accelerated_segment_payload,
    build_accelerated_split_stream_row_complete,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_target import (
    ScoreboardTurnLoader,
    load_accelerated_backfill_source_for_host_turn,
    observation_from_accelerated_segment,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
)
from api.analytics.military_score_inference.policy_ladder import (
    PolicyLadderState,
    finalize_policy_ladder_result,
)
from api.analytics.military_score_inference.row_complete_factory import (
    row_complete_from_accelerated_payload,
    row_complete_stopped,
)
from api.analytics.military_score_inference.solver import STATUS_TIME_LIMITED
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.models.game import TurnInfo
from api.models.player import Score


@dataclass(frozen=True)
class LadderSegmentAdvance:
    """Scheduler action after one accelerated segment's policy ladder finishes."""

    continue_next_segment: bool = False
    row_complete: RowComplete | None = None


@dataclass
class InferenceStreamOrchestration:
    """Mutable accelerated-segment state for one scheduled inference row."""

    path: InferencePath
    row_score: Score
    row_turn: TurnInfo
    solve_score: Score
    solve_turn: TurnInfo
    segments: tuple[AcceleratedInferenceSegment, ...]
    current_segment_index: int = 0
    segment_solves: list[AcceleratedSegmentSolve] = field(default_factory=list)
    combined_time_limited: bool = False
    backfill_target_host_turn: int | None = None
    backfill_source_turn_number: int | None = None

    @property
    def is_accelerated(self) -> bool:
        return self.path in (InferencePath.ACCELERATED_SPLIT, InferencePath.ACCELERATED_BACKFILL)

    @property
    def segment_payloads(self) -> list[dict[str, object]]:
        return [segment.payload for segment in self.segment_solves]

    def current_segment(self) -> AcceleratedInferenceSegment | None:
        if not self.is_accelerated or self.current_segment_index >= len(self.segments):
            return None
        return self.segments[self.current_segment_index]

    def current_observation(self) -> InferenceObservation:
        segment = self.current_segment()
        if segment is None:
            raise RuntimeError("accelerated stream orchestration has no active segment")
        return observation_from_accelerated_segment(self.solve_score, self.solve_turn, segment)

    def current_solve_turn(self) -> TurnInfo:
        return self.solve_turn

    def should_emit_streaming_solutions(self) -> bool:
        segment = self.current_segment()
        return segment is not None and segment.segment_id == "reported_host_turn"

    def new_ladder_state(self) -> PolicyLadderState:
        return PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)))

    def record_segment_ladder_complete(
        self,
        *,
        observation: InferenceObservation,
        result: InferenceResult,
        catalog: ActionCatalog | None,
        problem: InferenceProblem | None,
        policy_steps_attempted: list[str],
        step_diagnostics: list[dict[str, object]],
    ) -> None:
        segment = self.current_segment()
        if segment is None:
            return
        payload = build_accelerated_segment_payload(
            segment,
            observation,
            result,
            catalog,
            policy_steps_attempted=policy_steps_attempted,
            step_diagnostics=step_diagnostics,
        )
        self.segment_solves.append(
            AcceleratedSegmentSolve(
                segment=segment,
                observation=observation,
                result=result,
                catalog=catalog,
                problem=problem,
                policy_steps_attempted=policy_steps_attempted,
                step_diagnostics=step_diagnostics,
                payload=payload,
            )
        )
        if result.status == STATUS_TIME_LIMITED:
            self.combined_time_limited = True
        self.current_segment_index += 1

    def has_more_segments(self) -> bool:
        return self.is_accelerated and self.current_segment_index < len(self.segments)

    def _accelerated_stream_row_complete(self) -> AcceleratedStreamRowComplete:
        segment_solves = tuple(self.segment_solves)
        if self.path == InferencePath.ACCELERATED_BACKFILL:
            assert self.backfill_target_host_turn is not None
            assert self.backfill_source_turn_number is not None
            return build_accelerated_backfill_stream_row_complete(
                self.row_score,
                self.row_turn,
                target_host_turn=self.backfill_target_host_turn,
                source_turn_number=self.backfill_source_turn_number,
                source_turn=self.solve_turn,
                segment_solves=segment_solves,
            )
        return build_accelerated_split_stream_row_complete(
            self.row_score,
            self.row_turn,
            segment_solves=segment_solves,
            combined_time_limited=self.combined_time_limited,
        )

    def record_ladder_segment_complete(
        self,
        ladder_state: PolicyLadderState,
        observation: InferenceObservation,
        turn: TurnInfo,
    ) -> None:
        result, catalog, problem, policy_steps_attempted, step_diagnostics = (
            finalize_policy_ladder_result(ladder_state, observation, turn)
        )
        self.record_segment_ladder_complete(
            observation=observation,
            result=result,
            catalog=catalog,
            problem=problem,
            policy_steps_attempted=policy_steps_attempted,
            step_diagnostics=step_diagnostics,
        )

    def finish_ladder_segment(
        self,
        ladder_state: PolicyLadderState,
        observation: InferenceObservation,
        turn: TurnInfo,
    ) -> LadderSegmentAdvance:
        self.record_ladder_segment_complete(ladder_state, observation, turn)
        if self.has_more_segments():
            return LadderSegmentAdvance(continue_next_segment=True)
        return LadderSegmentAdvance(
            row_complete=row_complete_from_accelerated_payload(
                self._accelerated_stream_row_complete()
            )
        )

    def build_stopped_row_complete(
        self,
        ladder_state: PolicyLadderState | None,
        observation: InferenceObservation,
        turn: TurnInfo,
    ) -> RowComplete:
        if ladder_state is not None and ladder_state.catalog is not None:
            self.record_ladder_segment_complete(ladder_state, observation, turn)
        if self.segment_solves:
            return row_complete_stopped(
                base=row_complete_from_accelerated_payload(self._accelerated_stream_row_complete())
            )
        return row_complete_stopped(
            ladder_state=ladder_state,
            observation=observation,
            turn=turn,
        )


def create_inference_stream_orchestration(
    path: InferencePath,
    score: Score,
    turn: TurnInfo,
    *,
    segments: tuple[AcceleratedInferenceSegment, ...] | None,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> InferenceStreamOrchestration | None:
    """Build orchestration state for a schedulable inference row, if applicable."""
    if path == InferencePath.POLICY_LADDER:
        return None

    if path == InferencePath.ACCELERATED_SPLIT:
        if segments is None:
            return None
        return InferenceStreamOrchestration(
            path=path,
            row_score=score,
            row_turn=turn,
            solve_score=score,
            solve_turn=turn,
            segments=segments,
        )

    if path == InferencePath.ACCELERATED_BACKFILL:
        if load_scoreboard_turn is None:
            return None
        target_host_turn = scoreboard_host_turn(turn.settings.turn)
        if target_host_turn is None:
            return None
        backfill_source = load_accelerated_backfill_source_for_host_turn(
            score,
            turn,
            host_turn=target_host_turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if backfill_source is None:
            return None
        return InferenceStreamOrchestration(
            path=path,
            row_score=score,
            row_turn=turn,
            solve_score=backfill_source.source_score,
            solve_turn=backfill_source.source_turn,
            segments=backfill_source.segments,
            backfill_target_host_turn=target_host_turn,
            backfill_source_turn_number=backfill_source.source_turn_number,
        )

    return None
