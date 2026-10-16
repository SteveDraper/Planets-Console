"""InferenceSolution ids are process-local and stay off equality, repr, and wire."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from api.analytics.military_score_inference.inference_api_payload import (
    serialize_solution_without_arithmetic,
)
from api.analytics.military_score_inference.models import InferenceSolution, next_solution_id
from api.analytics.military_score_inference.tier_emission_ledger import compact_solution_emission


def _solution(objective_value: int = 1) -> InferenceSolution:
    return InferenceSolution(objective_value=objective_value, actions=())


def test_solution_ids_are_unique_and_ignored_by_equality_and_repr() -> None:
    first = _solution()
    second = _solution()
    assert second.solution_id == first.solution_id + 1
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert "solution_id" not in repr(first)
    replaced = replace(first, objective_value=first.objective_value)
    assert replaced == first
    assert replaced.solution_id != first.solution_id
    changed = replace(first, objective_value=first.objective_value + 1)
    assert changed != first
    assert changed.solution_id != first.solution_id


def test_solution_id_is_not_a_constructor_argument() -> None:
    with pytest.raises(TypeError):
        InferenceSolution(objective_value=1, actions=(), solution_id=4)  # type: ignore[call-arg]


def test_next_solution_id_feeds_constructed_solutions() -> None:
    before = _solution()
    allocated = next_solution_id()
    after = _solution()
    assert allocated == before.solution_id + 1
    assert after.solution_id == allocated + 1


def test_threaded_allocation_assigns_unique_solution_ids() -> None:
    allocated: list[int] = []
    lock = threading.Lock()

    def allocate() -> None:
        batch = [_solution().solution_id for _ in range(100)]
        with lock:
            allocated.extend(batch)

    threads = [threading.Thread(target=allocate) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allocated) == 800
    assert len(set(allocated)) == 800


def test_solution_id_is_omitted_from_wire_payloads() -> None:
    solution = _solution()
    core = serialize_solution_without_arithmetic(solution)
    emission = compact_solution_emission(solution)
    assert "solution_id" not in core
    assert "solutionId" not in core
    assert "solution_id" not in emission
    assert "solutionId" not in emission
