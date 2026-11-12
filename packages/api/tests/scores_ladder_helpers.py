"""A shell scoreboard tier ladder on an orchestrator whose pool never runs work.

``ShellLadder`` registers one player's RowRun through a live scores stream on a
real ``InferenceRowScheduler``, then runs the real scores ``tier_solve`` wire
builder and step with the tier job scripted.
"""

from __future__ import annotations

from unittest.mock import patch

from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeOrchestrator, ComputeRequest, ComputeScope, build_compute_registry
from api.compute.pools import ThreadStepWork

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.export_chain_test_fixtures import export_chain_query_context
from tests.scores_exports_helpers import GAME_ID, inference_target_player_id, perspective


def ladder_session(sample_turn, player_id: int) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )


def ladder_scope(sample_turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )


def durable_row_complete(summary: str) -> TierJobOutcome:
    return TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary=summary,
        ),
    )


class ShellLadder:
    """The shell scoreboard ladder for one player, opened through a live scores stream."""

    def __init__(self, sample_turn, persistence) -> None:
        self.player_id = inference_target_player_id(sample_turn)
        self.persistence = persistence
        self.scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
        self.stream_scope = InferenceStreamScope(
            game_id=GAME_ID,
            perspective=perspective(sample_turn),
            turn_number=sample_turn.settings.turn,
        )
        self.stream_token = self.scheduler.begin_scope(self.stream_scope)
        self.session = ladder_session(sample_turn, self.player_id)
        self.scheduler.enqueue_tier_ladder(self.session, stream_token=self.stream_token)
        self.ctx = export_chain_query_context(
            sample_turn,
            persistence=persistence,
            scheduler=self.scheduler,
            seed_fleet_prerequisites_for=self.player_id,
        )
        self.scope = ladder_scope(sample_turn, self.player_id)
        self.submitted_work: list[ThreadStepWork] = []
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION)),
            pool_submitter=lambda _node, _step, *, work: self.submitted_work.append(work),
        )
        self.tier_runs: list[str] = []

    def submit(self) -> None:
        self.orchestrator.submit(
            ComputeRequest(ctx=self.ctx, scope=self.scope, step_kind=SCORES_TIER_SOLVE)
        )
        assert self.orchestrator.nodes[self.scope].state == "running"

    def close_stream(self) -> None:
        """Run the stream's connect ``finally``: it detaches its own row."""
        self.scheduler.detach_inference_stream(
            self.stream_scope, (self.session,), stream_token=self.stream_token
        )

    def execute_tier(self, outcome: TierJobOutcome | BaseException) -> object:
        """Build and run the node's last submitted tier step on the worker.

        Returns the step's result wire. The orchestrator has not taken it yet,
        so nothing has persisted. A failing tier raises.
        """

        def tier_job(run: RowRun, _callbacks) -> TierJobOutcome:
            self.tier_runs.append(run.run_id)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch(
            "api.analytics.scores.compute_orchestration.run_inference_tier_job",
            side_effect=tier_job,
        ):
            return self.submitted_work[-1].run(self.scope)

    def complete_tier(self, result_wire: object) -> None:
        """Hand an executed step's result back to the orchestrator, which persists it."""
        complete_running_pool_step(self.orchestrator, self.scope, result_wire=result_wire)

    def run_tier(self, outcome: TierJobOutcome | BaseException) -> None:
        """Build and run the node's last submitted tier step, then hand the result back."""
        try:
            result_wire = self.execute_tier(outcome)
        except Exception as exc:
            complete_running_pool_step(self.orchestrator, self.scope, error=exc)
            return
        self.complete_tier(result_wire)

    def persisted_summary(self) -> str | None:
        row = self.persistence.get_row(
            GAME_ID, self.scope.perspective, self.scope.turn, self.player_id
        )
        return None if row is None else row.summary
