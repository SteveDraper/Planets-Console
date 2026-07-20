"""Guardrails against reintroducing thrash-era cancel/persist dual paths."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parents[1] / "api"

# Names retired by ADR 0006 / DAG_optimization thrash freeze. Must not reappear
# as bare identifiers in production packages/api/api.
_RETIRED_BARE_NAMES = (
    "unregister_row_run",
    "CancelFence",
    "cancel_fence_store",
    "known_run_allow",
    "DENY_CANCEL",
    "REFUSE_UNKNOWN",
    "SoftStreamAction",
    "mark_multiplex_closed",  # use stream_drain / _mark_multiplex_closed only
    "seal_canceled_finish",  # use stream_drain / _seal_canceled_finish only
    "RowRunPhase.CANCELLED",
    "snapshot_persist_decision",  # use decide_scores_row_persist only
)

_LIFECYCLE_MUTATOR_ALLOW = frozenset(
    {
        "analytics/scores/row_lifecycle.py",
        "analytics/scores/tier_row_run_registry.py",
    }
)
_DRAIN_HELPER_ALLOW = frozenset(
    {
        "streaming/table_stream/stream_drain.py",
        "streaming/table_stream/row_stream_resolution_registry.py",
    }
)


def _iter_production_py_files() -> list[Path]:
    return sorted(p for p in _API_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(_API_ROOT).as_posix()


@pytest.mark.parametrize("name", _RETIRED_BARE_NAMES)
def test_retired_thrash_names_absent_from_production(name: str) -> None:
    # Reject bare name but allow underscore-prefixed private helpers.
    compiled = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}\b")
    offenders = [
        _rel(path)
        for path in _iter_production_py_files()
        if compiled.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"{name!r} found in production: {offenders}"


def test_lifecycle_mutators_only_imported_by_row_lifecycle() -> None:
    """Adapters must not call registry-private shell mutators directly."""
    mutator = re.compile(
        r"from api\.analytics\.scores\.tier_row_run_registry import[^\n]*"
        r"(_detach_row_run|_mark_row_run_cancelled|_retire_row_run)"
    )
    offenders = [
        _rel(path)
        for path in _iter_production_py_files()
        if _rel(path) not in _LIFECYCLE_MUTATOR_ALLOW
        and mutator.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"lifecycle mutators imported outside allowlist: {offenders}"


def test_drain_helpers_only_imported_by_stream_drain() -> None:
    """Adapters must not call registry-private drain helpers directly."""
    helper = re.compile(
        r"from api\.streaming\.table_stream\.row_stream_resolution_registry import[^\n]*"
        r"(_mark_multiplex_closed|_seal_canceled_finish|"
        r"_is_multiplex_closed|_clear_multiplex_closed_if_soft)"
    )
    offenders = [
        _rel(path)
        for path in _iter_production_py_files()
        if _rel(path) not in _DRAIN_HELPER_ALLOW and helper.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"drain helpers imported outside allowlist: {offenders}"
