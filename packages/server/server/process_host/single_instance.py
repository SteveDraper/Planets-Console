"""Per-user lock so two process hosts cannot share one console data directory."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TextIO

LOCK_FILE_NAME = "process-host.lock"
PORT_FILE_NAME = "process-host.port"
_LOCK_BYTE_COUNT = 1


class SingleInstanceBusy(RuntimeError):
    """Another process host already holds the per-user lock."""


class SingleInstancePortError(RuntimeError):
    """The running process host did not publish a bound port in time."""


def _lock_exclusive(handle: TextIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTE_COUNT)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: TextIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTE_COUNT)
        except OSError:
            return
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_published_port_file(path: Path, payload: str) -> None:
    with open(path, "w", encoding="utf-8") as published:
        published.write(payload)
        published.flush()
        os.fsync(published.fileno())


class SingleInstanceLock:
    """Exclusive lock file in the console data directory.

    Bound port lives in an unlocked sidecar (``port_path``). Waiters read that
    file; they never open the lock file. Windows ``LockFile`` is mandatory, so
    a waiter ``Path.read_text`` of the locked lock file would fail.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.port_path = lock_path.with_name(PORT_FILE_NAME)
        self._handle: TextIO | None = None

    def try_acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+", encoding="utf-8")
        try:
            _lock_exclusive(handle)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        try:
            _write_published_port_file(self.port_path, "")
        except OSError:
            self.release()
            raise
        return True

    def write_bound_port(self, port: int) -> None:
        if self._handle is None:
            raise RuntimeError("write_bound_port requires an acquired lock")
        payload = json.dumps({"pid": os.getpid(), "port": port}, separators=(",", ":"))
        _write_published_port_file(self.port_path, payload)

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> SingleInstanceLock:
        if not self.try_acquire():
            raise SingleInstanceBusy(f"console package already running: {self.lock_path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def read_published_port(
    port_path: Path,
    *,
    timeout_seconds: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Read the bound port from the unlocked sidecar the lock holder publishes."""
    deadline = monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while monotonic() < deadline:
        try:
            raw = port_path.read_text(encoding="utf-8").strip()
            if raw:
                payload = json.loads(raw)
                port = payload["port"]
                if isinstance(port, int) and 1 <= port <= 65535:
                    return port
                last_error = SingleInstancePortError(f"invalid port in {port_path}: {port!r}")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            last_error = exc
        sleep(0.1)
    detail = f": {last_error}" if last_error is not None else ""
    raise SingleInstancePortError(f"Timed out waiting for a bound port in {port_path}{detail}")
