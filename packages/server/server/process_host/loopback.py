"""Loopback bind and listen-then-open for the process host."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable

LOOPBACK_HOST = "127.0.0.1"
PREFERRED_PORT = 8000
HEALTH_POLL_INTERVAL_SECONDS = 0.1
DEFAULT_HEALTH_TIMEOUT_SECONDS = 90.0
SPA_OPEN = webbrowser.open


class LoopbackBindError(RuntimeError):
    """No free loopback port was available."""


class HealthWaitError(RuntimeError):
    """GET /health did not succeed before the timeout."""


def spa_url(port: int) -> str:
    """SPA URL on the IPv4 loopback bind. Never uses the name localhost."""
    return f"http://{LOOPBACK_HOST}:{port}/"


def health_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}/health"


def next_free_loopback_port(start: int = PREFERRED_PORT) -> int:
    """Return the first free TCP port on 127.0.0.1 at or after ``start``."""
    if start < 1 or start > 65535:
        raise ValueError(f"start port must be in 1..65535, got {start}")
    for port in range(start, 65536):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((LOOPBACK_HOST, port))
            except OSError:
                continue
            return port
    raise LoopbackBindError(f"No free loopback port on {LOOPBACK_HOST} from {start} through 65535.")


def wait_for_health(
    port: int,
    *,
    timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    urlopen: Callable[..., object] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Block until GET /health on the bound loopback port returns HTTP 200."""
    url = health_url(port)
    deadline = monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                if status == 200:
                    return
                last_error = HealthWaitError(f"GET {url} returned HTTP {status}")
        except (urllib.error.URLError, TimeoutError, OSError, HealthWaitError) as exc:
            last_error = exc
        sleep(HEALTH_POLL_INTERVAL_SECONDS)
    detail = f": {last_error}" if last_error is not None else ""
    raise HealthWaitError(f"Timed out after {timeout_seconds:.0f}s waiting for GET {url}{detail}")


def open_spa(
    port: int,
    *,
    open_url: Callable[[str], object] = SPA_OPEN,
) -> None:
    """Open the default browser to the SPA after listen."""
    open_url(spa_url(port))
