"""Per-user process host lock file."""

from __future__ import annotations

import json
import os

import pytest
from server.process_host.single_instance import (
    LOCK_FILE_NAME,
    SingleInstanceLock,
    SingleInstancePortError,
    read_published_port,
)


def test_second_acquire_on_same_lock_file_fails(tmp_path):
    path = tmp_path / LOCK_FILE_NAME
    first = SingleInstanceLock(path)
    second = SingleInstanceLock(path)
    assert first.try_acquire() is True
    try:
        assert second.try_acquire() is False
        first.write_bound_port(8010)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["port"] == 8010
        assert payload["pid"] == os.getpid()
    finally:
        first.release()
    assert second.try_acquire() is True
    second.release()


def test_write_bound_port_round_trips_for_second_activation(tmp_path):
    path = tmp_path / "process-host.lock"
    holder = SingleInstanceLock(path)
    assert holder.try_acquire() is True
    try:
        holder.write_bound_port(8000)
        assert read_published_port(path, timeout_seconds=1.0, sleep=lambda _s: None) == 8000
    finally:
        holder.release()


def test_read_published_port_times_out_on_empty_file(tmp_path):
    path = tmp_path / "process-host.lock"
    path.write_text("", encoding="utf-8")
    times = iter([0.0, 0.5, 2.0])
    with pytest.raises(SingleInstancePortError, match="Timed out"):
        read_published_port(
            path,
            timeout_seconds=1.0,
            sleep=lambda _s: None,
            monotonic=lambda: next(times, 99.0),
        )
