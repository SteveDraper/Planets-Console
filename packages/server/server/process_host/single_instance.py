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


class SingleInstanceLock:
    """Exclusive lock file in the console data directory.

    The holder writes JSON ``{"pid": int, "port": int}`` after bind. A second
    activation that cannot acquire the lock reads that port and listen-then-opens.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            _lock_exclusive(handle)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def write_bound_port(self, port: int) -> None:
        if self._handle is None:
            raise RuntimeError("write_bound_port requires an acquired lock")
        payload = json.dumps({"pid": os.getpid(), "port": port}, separators=(",", ":"))
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(payload)
        self._handle.flush()
        os.fsync(self._handle.fileno())

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
            raise SingleInstanceBusy(f"console package already running: {self.path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def read_published_port(
    path: Path,
    *,
    timeout_seconds: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Read the bound port published by the process that holds the lock."""
    deadline = monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while monotonic() < deadline:
        try:
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                payload = json.loads(raw)
                port = payload["port"]
                if isinstance(port, int) and 1 <= port <= 65535:
                    return port
                last_error = SingleInstancePortError(f"invalid port in lock file: {port!r}")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            last_error = exc
        sleep(0.1)
    detail = f": {last_error}" if last_error is not None else ""
    raise SingleInstancePortError(f"Timed out waiting for a bound port in {path}{detail}")
