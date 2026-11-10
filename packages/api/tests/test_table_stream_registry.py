"""TableStreamRegistry: lock-free snapshot reads and compare-and-swap writers."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from api.streaming.table_stream.registry import TableStreamRegistry

READ_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class _Controller:
    stream_token: str


def _registry() -> TableStreamRegistry[str, _Controller]:
    return TableStreamRegistry[str, _Controller]()


def _detach(registry: TableStreamRegistry[str, _Controller], stream_token: str) -> None:
    registry.detach(stream_token, token_getter=lambda controller: controller.stream_token)


def test_attach_replaces_the_controller_for_a_scope_in_place():
    registry = _registry()
    first, replacement, other = _Controller("a1"), _Controller("a2"), _Controller("b")
    registry.attach("a", first)
    registry.attach("b", other)

    registry.attach("a", replacement)

    assert registry.items() == (("a", replacement), ("b", other))
    assert registry.controller_for_scope("a") is replacement
    assert registry.list_active_scopes() == ("a", "b")


def test_detach_by_token_removes_only_the_first_matching_controller():
    registry = _registry()
    registry.attach("a", _Controller("shared"))
    registry.attach("b", _Controller("shared"))
    registry.attach("c", _Controller("c"))

    _detach(registry, "shared")
    _detach(registry, "unknown")

    assert registry.list_active_scopes() == ("b", "c")
    assert registry.controller_for_scope("a") is None


def test_a_snapshot_already_read_does_not_change_when_a_writer_publishes():
    registry = _registry()
    registry.attach("a", _Controller("a"))
    before = registry.items()

    registry.attach("b", _Controller("b"))
    _detach(registry, "a")

    assert before == (("a", _Controller("a")),)


def test_readers_do_not_wait_for_a_writer_holding_the_lock():
    registry = _registry()
    controller = _Controller("a")
    registry.attach("a", controller)
    read = threading.Event()
    reads: list[object] = []

    def read_snapshot() -> None:
        reads.extend(
            (registry.items(), registry.controller_for_scope("a"), registry.list_active_scopes())
        )
        read.set()

    with registry._lock:
        threading.Thread(target=read_snapshot, daemon=True).start()
        assert read.wait(READ_TIMEOUT_SECONDS)

    assert reads == [(("a", controller),), controller, ("a",)]


def test_a_writer_that_loses_the_swap_retries_on_the_newer_snapshot():
    """The detach's token check runs outside the lock; an attach that lands
    during it is kept, and the detach still removes its controller."""
    registry = _registry()
    registry.attach("a", _Controller("a"))
    raced = _Controller("b")
    raced_once = False

    def token_with_racing_attach(controller: _Controller) -> str:
        nonlocal raced_once
        if not raced_once:
            raced_once = True
            registry.attach("b", raced)
        return controller.stream_token

    registry.detach("a", token_getter=token_with_racing_attach)

    assert registry.items() == (("b", raced),)


def test_concurrent_attach_and_detach_lose_no_update():
    registry = _registry()
    writer_count = 8
    scopes_per_writer = 50

    def write(writer: int) -> None:
        for index in range(scopes_per_writer):
            scope = f"{writer}-{index}"
            registry.attach(scope, _Controller(scope))
        for index in range(0, scopes_per_writer, 2):
            _detach(registry, f"{writer}-{index}")

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        for future in [pool.submit(write, writer) for writer in range(writer_count)]:
            future.result()

    assert set(registry.list_active_scopes()) == {
        f"{writer}-{index}"
        for writer in range(writer_count)
        for index in range(1, scopes_per_writer, 2)
    }
    assert all(controller.stream_token == scope for scope, controller in registry.items())


def test_reset_for_tests_clears_every_controller():
    registry = _registry()
    registry.attach("a", _Controller("a"))

    registry.reset_for_tests()

    assert registry.items() == ()
