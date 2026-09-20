"""Packaged SAT worker spawn executable (sibling binary, not the GUI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from api.analytics.scores.compute_plane.tier_solve_leaf import run_scores_tier_solve_leaf
from api.compute.process_pool_executable import (
    SAT_WORKER_STEM,
    apply_process_pool_executable,
    process_pool_executable,
    sat_worker_executable_name,
)
from api.compute.sat_worker_entry import spawn_targets
from api.compute.worker_turn_cache import init_worker_turn_cache

from tests.sat_worker_import_graph import (
    SAT_WORKER_DENIED_MODULE_PREFIXES,
    assert_fresh_import_avoids_sat_worker_denylist,
    denied_sat_worker_modules,
)


def test_sat_worker_executable_name_is_stem_or_windows_exe(monkeypatch):
    monkeypatch.setattr("api.compute.process_pool_executable.sys.platform", "darwin")
    assert sat_worker_executable_name() == SAT_WORKER_STEM
    monkeypatch.setattr("api.compute.process_pool_executable.sys.platform", "win32")
    assert sat_worker_executable_name() == f"{SAT_WORKER_STEM}.exe"


def test_process_pool_executable_none_when_unpackaged(monkeypatch):
    monkeypatch.setattr("api.compute.process_pool_executable.process_is_frozen", lambda: False)
    assert process_pool_executable() is None
    assert apply_process_pool_executable() is None


def test_process_pool_executable_frozen_uses_sibling_not_gui(monkeypatch, tmp_path):
    gui = tmp_path / "Planets Console"
    gui.write_bytes(b"")
    worker = tmp_path / sat_worker_executable_name()
    worker.write_bytes(b"")
    monkeypatch.setattr("api.compute.process_pool_executable.process_is_frozen", lambda: True)
    monkeypatch.setattr("api.compute.process_pool_executable.sys.executable", str(gui))
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "api.compute.process_pool_executable.multiprocessing.set_executable",
        lambda path: captured.update(executable=path),
    )

    path = apply_process_pool_executable()

    assert path == str(worker.resolve())
    assert captured["executable"] == path
    assert captured["executable"] != str(gui)
    assert Path(captured["executable"]).name == sat_worker_executable_name()


def test_process_pool_executable_frozen_missing_worker_raises(monkeypatch, tmp_path):
    gui = tmp_path / "Planets Console"
    gui.write_bytes(b"")
    monkeypatch.setattr("api.compute.process_pool_executable.process_is_frozen", lambda: True)
    monkeypatch.setattr("api.compute.process_pool_executable.sys.executable", str(gui))
    with pytest.raises(RuntimeError, match="windowed process host"):
        process_pool_executable()


def test_sat_worker_denied_prefixes_cover_http_and_parent_plane():
    prefixes = set(SAT_WORKER_DENIED_MODULE_PREFIXES)
    assert {
        "AppKit",
        "api.analytics.export_context",
        "api.analytics.scores.compute_orchestration",
        "api.app",
        "api.errors",
        "bff",
        "fastapi",
        "server.app",
        "server.process_host",
        "starlette",
        "uvicorn",
    } <= prefixes
    loaded = (
        "fastapi",
        "fastapi.routing",
        "starlette",
        "api.apple",
        "api.app",
        "bff.analytics",
        "api.analytics.export_context",
    )
    assert denied_sat_worker_modules(loaded) == [
        "fastapi",
        "fastapi.routing",
        "starlette",
        "api.app",
        "bff.analytics",
        "api.analytics.export_context",
    ]


def test_sat_worker_entry_import_does_not_load_http_or_parent_plane():
    assert_fresh_import_avoids_sat_worker_denylist(
        import_line="from api.compute.sat_worker_entry import spawn_targets",
        exported_name="spawn_targets",
    )


def test_spawn_targets_are_leaf_and_turn_cache_init():
    assert spawn_targets() == (run_scores_tier_solve_leaf, init_worker_turn_cache)
