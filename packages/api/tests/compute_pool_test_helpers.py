"""Module-level helpers for compute pool integration tests (shareable run_step)."""

from __future__ import annotations

INTERPRETER_BACKEND_CALLS: list[str] = []
PROCESS_BACKEND_CALLS: list[str] = []


def run_interpreter_materialize(job: dict[str, str]) -> dict[str, str]:
    INTERPRETER_BACKEND_CALLS.append(job["scope"])
    return {"result": job["scope"]}


def run_process_materialize(job: dict[str, str]) -> dict[str, str]:
    PROCESS_BACKEND_CALLS.append(job["scope"])
    return {"result": job["scope"]}
