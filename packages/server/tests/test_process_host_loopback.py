"""Process host loopback bind and listen-then-open."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock
from urllib.error import URLError

import pytest
from server.process_host.loopback import (
    LOOPBACK_HOST,
    PREFERRED_PORT,
    HealthWaitError,
    health_url,
    next_free_loopback_port,
    open_spa,
    spa_url,
    wait_for_health,
)


class _HealthOkResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return 200


def test_spa_and_health_urls_use_ipv4_loopback_never_localhost():
    assert spa_url(8000) == "http://127.0.0.1:8000/"
    assert health_url(8000) == "http://127.0.0.1:8000/health"
    assert "localhost" not in spa_url(9000)
    assert "localhost" not in health_url(9000)
    assert LOOPBACK_HOST == "127.0.0.1"


def test_next_free_loopback_port_returns_preferred_when_free():
    port = next_free_loopback_port(PREFERRED_PORT)
    assert port >= PREFERRED_PORT
    assert 1 <= port <= 65535


def test_next_free_loopback_port_skips_occupied_preferred():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind((LOOPBACK_HOST, 0))
    taken = occupied.getsockname()[1]
    try:
        free = next_free_loopback_port(taken)
        assert free != taken
        assert free > taken
    finally:
        occupied.close()


def test_wait_for_health_returns_without_sleep_when_already_up():
    slept: list[float] = []

    wait_for_health(
        8000,
        timeout_seconds=2.0,
        urlopen=lambda _url, timeout=1.0: _HealthOkResponse(),
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )
    assert slept == []


def test_wait_for_health_succeeds_on_http_200():
    calls = {"n": 0}
    clock = {"t": 0.0}

    def urlopen(url, timeout=1.0):
        calls["n"] += 1
        assert url == "http://127.0.0.1:8123/health"
        if calls["n"] == 1:
            raise URLError("connection refused")
        return _HealthOkResponse()

    def monotonic():
        current = clock["t"]
        clock["t"] += 0.1
        return current

    wait_for_health(
        8123,
        timeout_seconds=2.0,
        urlopen=urlopen,
        sleep=lambda _s: None,
        monotonic=monotonic,
    )
    assert calls["n"] == 2


def test_wait_for_health_times_out():
    def urlopen(url, timeout=1.0):
        raise URLError("connection refused")

    times = iter([0.0, 0.5, 1.1])
    with pytest.raises(HealthWaitError, match="Timed out"):
        wait_for_health(
            8000,
            timeout_seconds=1.0,
            urlopen=urlopen,
            sleep=lambda _s: None,
            monotonic=lambda: next(times, 99.0),
        )


def test_open_spa_opens_loopback_slash_url():
    opened: list[str] = []
    open_spa(8001, open_url=opened.append)
    assert opened == ["http://127.0.0.1:8001/"]
    mock = MagicMock()
    open_spa(8000, open_url=mock)
    mock.assert_called_once_with("http://127.0.0.1:8000/")
