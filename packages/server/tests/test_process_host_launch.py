"""Console package launch contract: listen-then-open, single-instance, start failure."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from api import config as api_config
from bff import config as bff_config
from server.process_host.loopback import HealthWaitError
from server.process_host.runtime import _configure_packaged_server, _run, _run_as_primary, main
from server.process_host.single_instance import LOCK_FILE_NAME, SingleInstanceLock
from server.process_host.support import StartFailure, show_start_failure


@pytest.fixture
def restore_layer_config():
    api_before = api_config._config
    bff_before = bff_config._config
    yield
    api_config._config = api_before
    bff_config._config = bff_before


class _FakeUvicornServer:
    should_exit = False

    def run(self) -> None:
        return None


def _stub_primary_server(monkeypatch, tmp_path, *, wait_for_health, open_spa) -> None:
    dist = tmp_path / "spa"
    dist.mkdir()
    monkeypatch.setattr("server.process_host.runtime.apply_frontend_dist_env", lambda: dist)
    monkeypatch.setattr(
        "server.process_host.runtime.next_free_loopback_port",
        lambda start=8000: 8123,
    )
    monkeypatch.setattr("server.process_host.runtime._configure_packaged_server", lambda port: None)
    monkeypatch.setattr(
        "server.process_host.runtime._build_uvicorn_server",
        lambda port: _FakeUvicornServer(),
    )
    monkeypatch.setattr("server.process_host.runtime.wait_for_health", wait_for_health)
    monkeypatch.setattr("server.process_host.runtime.open_spa", open_spa)
    monkeypatch.setattr("server.process_host.runtime._run_native_loop", lambda session: None)


def test_run_as_primary_opens_spa_only_after_health_on_loopback(tmp_path, monkeypatch):
    events: list[tuple[str, ...]] = []

    def wait_for_health(port, **_kwargs):
        events.append(("health", port))

    def open_spa(port):
        events.append(("open", port))

    class RecordingThread(threading.Thread):
        def start(self):
            events.append(("start",))
            super().start()

    _stub_primary_server(
        monkeypatch,
        tmp_path,
        wait_for_health=wait_for_health,
        open_spa=open_spa,
    )
    monkeypatch.setattr("server.process_host.runtime.threading.Thread", RecordingThread)
    lock = MagicMock()
    log_path = tmp_path / "logs" / "process-host.log"

    assert _run_as_primary(lock, log_path) == 0

    lock.write_bound_port.assert_called_once_with(8123)
    assert events == [("start",), ("health", 8123), ("open", 8123)]


def test_run_as_primary_does_not_open_spa_when_health_never_succeeds(tmp_path, monkeypatch):
    opened: list[int] = []

    def wait_for_health(port, **_kwargs):
        raise HealthWaitError(f"Timed out waiting for GET http://127.0.0.1:{port}/health")

    _stub_primary_server(
        monkeypatch,
        tmp_path,
        wait_for_health=wait_for_health,
        open_spa=opened.append,
    )
    lock = MagicMock()
    log_path = tmp_path / "logs" / "process-host.log"

    with pytest.raises(StartFailure, match="did not become ready") as caught:
        _run_as_primary(lock, log_path)

    assert opened == []
    assert str(log_path) in str(caught.value)
    assert "http://127.0.0.1:8123/health" in str(caught.value)


def test_second_activation_does_not_start_a_second_server(tmp_path, monkeypatch):
    monkeypatch.setattr("server.process_host.runtime.console_data_directory", lambda: tmp_path)
    monkeypatch.setattr(
        "server.process_host.runtime.configure_support_logging",
        lambda _data_dir: tmp_path / "logs" / "process-host.log",
    )
    primary_started: list[str] = []
    monkeypatch.setattr(
        "server.process_host.runtime._run_as_primary",
        lambda *_args, **_kwargs: primary_started.append("started") or 0,
    )
    monkeypatch.setattr(
        "server.process_host.runtime._reopen_existing_instance",
        lambda _port_path: 0,
    )
    holder = SingleInstanceLock(tmp_path / LOCK_FILE_NAME)
    assert holder.try_acquire() is True
    try:
        assert _run() == 0
        assert primary_started == []
    finally:
        holder.release()


def test_configure_packaged_server_storage_root_is_console_data_directory(
    tmp_path, monkeypatch, restore_layer_config
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".data").mkdir()
    (tmp_path / ".config.yaml").write_text(
        "api:\n  storage_backend: file\n  storage_root: ./.data\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "Library" / "Application Support" / "Planets Console"
    monkeypatch.setattr(
        "server.console_data_directory.console_data_directory",
        lambda: data_dir,
    )

    _configure_packaged_server(8123)

    assert api_config.get_config().storage_backend == "file"
    assert api_config.get_config().storage_root == str(data_dir)
    assert api_config.get_config().storage_root != "./.data"


def test_main_shows_start_failure_and_returns_one(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "server.process_host.runtime._run",
        lambda: (_ for _ in ()).throw(StartFailure("Could not bind 127.0.0.1")),
    )
    monkeypatch.setattr(
        "server.process_host.runtime.show_start_failure",
        shown.append,
    )

    assert main() == 1
    assert shown == ["Could not bind 127.0.0.1"]


def test_main_unexpected_error_shows_dialog_pointing_at_data_folder(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "server.process_host.runtime._run",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr("server.process_host.runtime.show_start_failure", shown.append)

    assert main() == 1
    assert shown
    assert "Planets Console could not start" in shown[0]
    assert "boom" in shown[0]
    assert "data folder" in shown[0].lower()


def test_run_writes_support_log_under_data_directory_when_spa_missing(tmp_path, monkeypatch):
    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setattr("server.process_host.runtime.console_data_directory", lambda: tmp_path)
    monkeypatch.setattr(
        "server.process_host.runtime.apply_frontend_dist_env",
        lambda: tmp_path / "missing-spa",
    )
    try:
        with pytest.raises(StartFailure, match="web UI"):
            _run()
        log_path = tmp_path / "logs" / "process-host.log"
        assert log_path.is_file()
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_start_failure_macos_dialog_contract(monkeypatch):
    monkeypatch.setattr("server.process_host.support.sys.platform", "darwin")
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("server.process_host.support.subprocess.run", fake_run)
    show_start_failure('Could not bind "loopback"')

    args = captured["args"]
    assert args[0] == "osascript"
    assert args[1] == "-e"
    script = args[2]
    assert 'with title "Planets Console"' in script
    assert r"Could not bind \"loopback\"" in script
    assert 'buttons {"OK"}' in script
    assert 'default button "OK"' in script
    assert "with icon stop" in script
    assert captured["kwargs"]["capture_output"] is True


def test_start_failure_windows_dialog_contract(monkeypatch):
    monkeypatch.setattr("server.process_host.support.sys.platform", "win32")
    called: dict[str, object] = {}

    class FakeUser32:
        @staticmethod
        def MessageBoxW(hwnd, text, caption, flags):
            called["args"] = (hwnd, text, caption, flags)
            return 1

    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
        raising=False,
    )
    show_start_failure("Could not bind 127.0.0.1")

    assert called["args"] == (
        None,
        "Could not bind 127.0.0.1",
        "Planets Console",
        0x10,
    )
