"""Shared fixtures for compute orchestrator tests: registrations, scopes and persistence policies.

Registrations here are minimal single-step analytics keyed by row scope
(perspective, turn, player). Pair them with the diamond export fixture
(``tests.fixtures.export_framework``) for dependency edges, and with
``tests.compute_pool_test_helpers`` to drive pool steps by hand.
:class:`ArmableRootPlanHook` lands test actions inside one later submission.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeScope,
    ComputeStepSpec,
    ScopeKeySpec,
    normalize_export_scope_to_compute_scope,
)
from api.compute.profile import ComputeBackend
from api.compute.root_plan import RootPlan, open_ignored_root_plan
from api.compute.submission_open import SubmissionOpen

from tests.compute_pool_test_helpers import (
    run_interpreter_materialize,
    run_process_materialize,
)
from tests.fixtures.export_framework.harness import first_player_id

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.dag import PlannedComputeNode

ROW_SCOPE_KEY = ScopeKeySpec(axes=("perspective", "turn", "player_id"))


class StubPersistencePolicy:
    """A persistence policy that is never satisfied, persists nothing and never invalidates."""

    def is_satisfied(self, _ctx, _scope) -> bool:
        return False

    def satisfied_result_wire(self, _ctx, _scope) -> None:
        return None

    def persist(self, _ctx, _scope, _result_wire) -> None:
        return None

    def invalidate(self, _ctx, _scope) -> None:
        return None

    def invalidation_generation(self, _ctx, _scope) -> int:
        return 0


class RecordingPersistencePolicy:
    """A persistence policy that records persists and whose ``invalidate`` moves the generation.

    Calling ``invalidate`` while a step runs makes that step epoch-stale when
    it finishes. One instance shares one generation across every scope it
    serves, so give each analytic its own instance when only one should go
    stale.
    """

    def __init__(self) -> None:
        self.generation = 0
        self.persist_calls: list[tuple[ComputeScope, object]] = []

    def is_satisfied(self, _ctx, _scope) -> bool:
        return False

    def satisfied_result_wire(self, _ctx, _scope) -> None:
        return None

    def persist(self, _ctx, scope, result_wire) -> None:
        self.persist_calls.append((scope, result_wire))

    def invalidate(self, _ctx, _scope) -> None:
        self.generation += 1

    def invalidation_generation(self, _ctx, _scope) -> int:
        return self.generation


def catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name=analytic_id,
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def inline_compute_registration(
    analytic_id: str,
    *,
    step_kind: str = "materialize",
) -> TurnAnalyticRegistration:
    """A single inline step that returns ``{"result": <analytic id>}``."""
    return TurnAnalyticRegistration(
        catalog_entry=catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind=step_kind, backend="inline"),),
        ),
        persistence_policy=StubPersistencePolicy(),
        build_step_job_wires=(
            (
                step_kind,
                lambda scope, **_kwargs: {"scope": scope.analytic_id},
            ),
        ),
        run_steps=(
            (
                step_kind,
                lambda job: {"result": job["scope"]},
            ),
        ),
    )


def _pool_run_step_for_backend(backend: ComputeBackend):
    if backend == "thread":
        return lambda job: {"result": job["scope"]}
    if backend == "interpreter":
        return run_interpreter_materialize
    if backend == "process":
        return run_process_materialize
    raise ValueError(f"unsupported pool backend {backend!r}")


def pool_compute_registration(
    analytic_id: str,
    *,
    backend: ComputeBackend,
    persistence_policy: object | None = None,
) -> TurnAnalyticRegistration:
    """A single ``materialize`` step on the pool ``backend``."""
    return TurnAnalyticRegistration(
        catalog_entry=catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend=backend),),
        ),
        persistence_policy=persistence_policy or StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", _pool_run_step_for_backend(backend)),),
    )


def make_export_scope(sample_turn) -> ExportScope:
    """The export scope of ``sample_turn`` for perspective 1 and its first player."""
    return ExportScope(
        game_id=sample_turn.game.id,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )


def make_compute_scope(analytic_id: str, export_scope: ExportScope) -> ComputeScope:
    """``export_scope`` normalized to ``analytic_id``'s row compute scope."""
    return normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id=analytic_id,
        scope_key_spec=ROW_SCOPE_KEY,
    )


RootPlanAction = Callable[[], None]


def _no_root_plan_action() -> None:
    return None


@dataclass(frozen=True)
class _ArmedRootPlanActions:
    on_enter: RootPlanAction
    on_registered: RootPlanAction
    on_exit: RootPlanAction


@dataclass(frozen=True)
class _ActingRootPlan:
    """The ignored root plan, running ``on_registered`` when its plan registers."""

    inner: RootPlan
    on_registered: RootPlanAction

    @property
    def submission_open(self) -> SubmissionOpen:
        return self.inner.submission_open

    def plan_registered(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        self.inner.plan_registered(planned)
        self.on_registered()


class ArmableRootPlanHook:
    """An ``open_root_plan`` hook that runs armed actions around the next root plan it opens.

    Install it as a registration's ``open_root_plan``. Unarmed, it behaves as
    :func:`open_ignored_root_plan`. :meth:`arm` sets actions for the next
    submission rooted at that analytic; the hook disarms as it opens that
    plan, so a submission an action makes opens an unarmed plan.

    ``on_enter`` runs as the plan opens, outside the orchestrator lock and
    before the dependency chain is prepared, so it may submit or abort.
    ``on_registered`` runs under the lock in the hold that registers the
    plan, so it must not call back into the orchestrator. ``on_exit`` runs as
    the plan closes after a clean submission. Any of them may raise.
    """

    def __init__(self) -> None:
        self._armed: _ArmedRootPlanActions | None = None

    def arm(
        self,
        *,
        on_enter: RootPlanAction = _no_root_plan_action,
        on_registered: RootPlanAction = _no_root_plan_action,
        on_exit: RootPlanAction = _no_root_plan_action,
    ) -> None:
        self._armed = _ArmedRootPlanActions(on_enter, on_registered, on_exit)

    def __call__(
        self,
        scope: ComputeScope,
        submission_open: SubmissionOpen,
        ctx: AnalyticQueryContext,
    ) -> AbstractContextManager[RootPlan]:
        actions, self._armed = self._armed, None
        ignored = open_ignored_root_plan(scope, submission_open, ctx)
        if actions is None:
            return ignored
        return _acting_root_plan(ignored, actions)


@contextmanager
def _acting_root_plan(
    ignored: AbstractContextManager[RootPlan],
    actions: _ArmedRootPlanActions,
) -> Iterator[RootPlan]:
    with ignored as inner:
        actions.on_enter()
        yield _ActingRootPlan(inner, actions.on_registered)
        actions.on_exit()
