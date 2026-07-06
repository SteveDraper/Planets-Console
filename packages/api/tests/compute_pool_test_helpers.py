"""Module-level helpers for compute pool integration tests (shareable run_step)."""

from __future__ import annotations


def run_interpreter_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}


def run_process_materialize(job: dict[str, str]) -> dict[str, str]:
    return {"result": job["scope"]}
