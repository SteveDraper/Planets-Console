"""Homeworld export ensure reports orchestrator chain-fill failures in its own wording."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from api.analytics.export_turn_fill import ChainFillReason, DependencyChainFillError
from api.analytics.export_types import ExportScope
from api.analytics.homeworld_locator import exports
from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    clear_ensure_failure_reports,
    recent_ensure_failure_reports,
)
from api.concepts.homeworld_layout import is_homeworld_locator_available
from api.errors import ValidationError
from api.models.game import TurnInfo

from tests.homeworld_locator_test_helpers import load_sample_turn

SCOPE = ExportScope(game_id=628580, perspective=1, turn=5)


@dataclass
class _EnsureContext:
    """The slice of a query context ``ensure_homeworld_export`` reads past its satisfaction gate."""

    shell_turn: TurnInfo
    invalidated_scopes: list[tuple[str, ExportScope]] = field(default_factory=list)

    def load_turn(self, turn_number: int) -> TurnInfo | None:
        return self.shell_turn if turn_number == SCOPE.turn else None

    def invalidate_export_scope_cache(self, analytic_id: str, scope: ExportScope) -> None:
        self.invalidated_scopes.append((analytic_id, scope))


@pytest.fixture
def ensure_context(monkeypatch) -> _EnsureContext:
    shell_turn = load_sample_turn()
    assert is_homeworld_locator_available(shell_turn.settings)
    monkeypatch.setattr(exports, "is_homeworld_export_ensure_satisfied", lambda ctx, scope: False)
    clear_ensure_failure_reports()
    return _EnsureContext(shell_turn=shell_turn)


def _orchestrator_ensure_raising(error: DependencyChainFillError):
    def ensure_export_scope_via_orchestrator(ctx, analytic_id, scope):
        raise error

    return ensure_export_scope_via_orchestrator


@pytest.mark.parametrize(
    ("reason", "missing_turn", "detail"),
    [
        (
            "turn_not_stored",
            3,
            "turn 3 is not stored (sign in to auto-fetch missing turns for the evidence chain)",
        ),
        (
            "turn_fetch_failed",
            4,
            "could not load turn 4 from Planets.nu (required for the evidence chain)",
        ),
        ("ensure_cycle", None, "turn unavailable (ensure_cycle)"),
    ],
)
def test_chain_fill_failure_is_recorded_with_the_homeworld_prefix(
    monkeypatch,
    ensure_context: _EnsureContext,
    reason: ChainFillReason,
    missing_turn: int | None,
    detail: str,
) -> None:
    import api.compute.export_ensure as export_ensure

    monkeypatch.setattr(
        export_ensure,
        "ensure_export_scope_via_orchestrator",
        _orchestrator_ensure_raising(
            DependencyChainFillError(detail, reason=reason, missing_turn=missing_turn)
        ),
    )
    expected_message = f"homeworld locator cannot refine turn {SCOPE.turn}: {detail}"

    with pytest.raises(ValidationError) as raised:
        exports.ensure_homeworld_export(ensure_context, SCOPE)

    assert str(raised.value) == expected_message
    assert not isinstance(raised.value, DependencyChainFillError)
    failures = recent_ensure_failure_reports(game_id=SCOPE.game_id, perspective=SCOPE.perspective)
    assert [(failure.reason, failure.missing_turn, failure.message) for failure in failures] == [
        (reason, missing_turn, expected_message)
    ]
    assert failures[0].shell_turn == SCOPE.turn
    assert ensure_context.invalidated_scopes == []


def test_successful_ensure_invalidates_the_export_scope_cache(
    monkeypatch,
    ensure_context: _EnsureContext,
) -> None:
    import api.compute.export_ensure as export_ensure

    monkeypatch.setattr(
        export_ensure,
        "ensure_export_scope_via_orchestrator",
        lambda ctx, analytic_id, scope: True,
    )

    assert exports.ensure_homeworld_export(ensure_context, SCOPE) is True
    assert ensure_context.invalidated_scopes == [(exports.ANALYTIC_ID, SCOPE)]
    assert recent_ensure_failure_reports(game_id=SCOPE.game_id, perspective=SCOPE.perspective) == ()
