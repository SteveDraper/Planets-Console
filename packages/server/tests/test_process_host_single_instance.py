"""Per-user process host lock file and unlocked port sidecar."""

from __future__ import annotations

import json
import os

import pytest
from server.process_host.runtime import _reopen_existing_instance, _run
from server.process_host.single_instance import (
    LOCK_FILE_NAME,
    PORT_FILE_NAME,
    SingleInstanceLock,
    SingleInstancePortError,
    read_published_port,
)


def _timeout_clock():
    times = iter([0.0, 0.5, 2.0])
    return lambda: next(times, 99.0)


def test_second_acquire_on_same_lock_file_fails(tmp_path):
    lock_path = tmp_path / LOCK_FILE_NAME
    first = SingleInstanceLock(lock_path)
    second = SingleInstanceLock(lock_path)
    assert first.try_acquire() is True
    try:
        assert second.try_acquire() is False
        first.write_bound_port(8010)
        payload = json.loads(first.port_path.read_text(encoding="utf-8"))
        assert payload["port"] == 8010
        assert payload["pid"] == os.getpid()
    finally:
        first.release()
    assert second.try_acquire() is True
    second.release()


def test_waiter_reads_unlocked_sidecar_while_lock_held(tmp_path):
    holder = SingleInstanceLock(tmp_path / LOCK_FILE_NAME)
    assert holder.try_acquire() is True
    try:
        holder.write_bound_port(8000)
        assert holder.port_path != holder.lock_path
        assert holder.port_path.name == PORT_FILE_NAME
        assert (
            read_published_port(holder.port_path, timeout_seconds=1.0, sleep=lambda _s: None)
            == 8000
        )
    finally:
        holder.release()
    # Sidecar is the publication channel; the lock file is not read while held
    # (Windows LockFile would reject that) and does not carry the bound port.
    assert "8000" not in holder.lock_path.read_text(encoding="utf-8")


def test_acquire_clears_stale_published_port_before_write(tmp_path):
    holder = SingleInstanceLock(tmp_path / LOCK_FILE_NAME)
    holder.port_path.write_text(
        json.dumps({"pid": 1, "port": 9999}),
        encoding="utf-8",
    )
    assert holder.try_acquire() is True
    try:
        with pytest.raises(SingleInstancePortError, match="Timed out"):
            read_published_port(
                holder.port_path,
                timeout_seconds=1.0,
                sleep=lambda _s: None,
                monotonic=_timeout_clock(),
            )
        holder.write_bound_port(8000)
        assert (
            read_published_port(holder.port_path, timeout_seconds=1.0, sleep=lambda _s: None)
            == 8000
        )
    finally:
        holder.release()


def test_read_published_port_times_out_on_empty_file(tmp_path):
    port_path = tmp_path / PORT_FILE_NAME
    port_path.write_text("", encoding="utf-8")
    with pytest.raises(SingleInstancePortError, match="Timed out"):
        read_published_port(
            port_path,
            timeout_seconds=1.0,
            sleep=lambda _s: None,
            monotonic=_timeout_clock(),
        )


def test_runtime_second_activation_reads_port_sidecar(tmp_path, monkeypatch):
    port_path = tmp_path / PORT_FILE_NAME
    port_path.write_text(json.dumps({"pid": 1, "port": 8123}), encoding="utf-8")
    opened: list[int] = []
    monkeypatch.setattr(
        "server.process_host.runtime.wait_for_health",
        lambda port, timeout_seconds=30.0: None,
    )
    monkeypatch.setattr(
        "server.process_host.runtime.open_spa",
        lambda port: opened.append(port),
    )
    assert _reopen_existing_instance(port_path) == 0
    assert opened == [8123]


def test_run_passes_sidecar_when_lock_is_held(tmp_path, monkeypatch):
    monkeypatch.setattr("server.process_host.runtime.console_data_directory", lambda: tmp_path)
    monkeypatch.setattr(
        "server.process_host.runtime.configure_support_logging",
        lambda _data_dir: tmp_path / "logs" / "process-host.log",
    )
    seen: dict[str, object] = {}

    def fake_reopen(port_path):
        seen["port_path"] = port_path
        return 0

    monkeypatch.setattr("server.process_host.runtime._reopen_existing_instance", fake_reopen)
    holder = SingleInstanceLock(tmp_path / LOCK_FILE_NAME)
    assert holder.try_acquire() is True
    try:
        assert _run() == 0
        assert seen["port_path"] == holder.port_path
    finally:
        holder.release()
