"""Shared denylist for slim SAT worker and scores ``tier_solve`` leaf imports."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# HTTP/GUI stack, parent scores orchestration, turn/storage rebuild, and BFF.
SAT_WORKER_DENIED_MODULE_PREFIXES: tuple[str, ...] = (
    "AppKit",
    "api.analytics.export_context",
    "api.analytics.military_score_inference.policy_ladder",
    "api.analytics.military_score_inference.policy_ladder_state",
    "api.analytics.military_score_inference.policy_ladder_tier_step",
    "api.analytics.military_score_inference.row_run",
    "api.analytics.scores.compute_orchestration",
    "api.app",
    "api.compute.pools",
    "api.compute.sat_session_submit",
    "api.compute.turn_cache",
    "api.compute.worker_turn_cache",
    "api.errors",
    "api.serialization.turn",
    "api.storage.file",
    "bff",
    "fastapi",
    "server.app",
    "server.process_host",
    "starlette",
    "uvicorn",
)

_API_ROOT = Path(__file__).resolve().parent.parent


def denied_sat_worker_modules(loaded: Iterable[str]) -> list[str]:
    """Return loaded names that equal a denied prefix or live under one."""
    blocked: list[str] = []
    for name in loaded:
        for prefix in SAT_WORKER_DENIED_MODULE_PREFIXES:
            if name == prefix or name.startswith(f"{prefix}."):
                blocked.append(name)
                break
    return blocked


def assert_fresh_import_avoids_sat_worker_denylist(
    *,
    import_line: str,
    exported_name: str,
) -> None:
    """Fail if a fresh interpreter import of the worker or leaf loads a denied module."""
    script = f"""
{import_line}
import sys
from tests.sat_worker_import_graph import denied_sat_worker_modules
blocked = denied_sat_worker_modules(sys.modules)
if blocked:
    raise SystemExit(f"unexpected modules: {{blocked}}")
if {exported_name} is None:
    raise SystemExit({exported_name!r} + " missing")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_API_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
