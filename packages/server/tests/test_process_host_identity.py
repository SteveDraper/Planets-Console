"""Packaged identity, bundled SPA path, and OS Quit -> uvicorn.should_exit."""

from __future__ import annotations

import logging
import os
import threading
from unittest.mock import MagicMock, patch

from server.package_identity import (
    APP_USER_MODEL_ID,
    CFBUNDLE_IDENTIFIER,
    CONSOLE_PACKAGE_DISPLAY_NAME,
    console_package_version,
)
from server.process_host.bundled_paths import (
    FRONTEND_DIST_ENV,
    apply_frontend_dist_env,
    resource_root,
    spa_dist_dir,
)
from server.process_host.native_windows import SC_RESTORE, _sys_command
from server.process_host.runtime import ProcessHostSession
from server.process_host.support import configure_support_logging, show_start_failure


def test_package_identity_matches_adr_0029():
    assert CONSOLE_PACKAGE_DISPLAY_NAME == "Planets Console"
    assert CFBUNDLE_IDENTIFIER == "com.github.stevedraper.planets-console"
    assert APP_USER_MODEL_ID == "SteveDraper.PlanetsConsole"
    version = console_package_version()
    assert version == "0.1.0"
    assert version != "0.1"


def test_apply_frontend_dist_env_uses_meipass_when_frozen(tmp_path, monkeypatch):
    meipass = tmp_path / "_internal"
    dist = meipass / "packages" / "frontend" / "dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr("server.process_host.bundled_paths.is_frozen", lambda: True)
    monkeypatch.setattr("sys._MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv(FRONTEND_DIST_ENV, "")
    assert resource_root() == meipass
    apply_frontend_dist_env()
    assert os.environ[FRONTEND_DIST_ENV] == str(dist)


def test_spa_dist_dir_under_source_repo_contains_packages_frontend_dist():
    path = spa_dist_dir()
    assert path.parts[-3:] == ("packages", "frontend", "dist")


def test_request_stop_sets_uvicorn_should_exit():
    server = MagicMock()
    session = ProcessHostSession(port=8000, server=server, stop_event=threading.Event())
    session.request_stop()
    assert session.stop_event.is_set()
    assert server.should_exit is True


def test_start_failure_dialog_uses_injected_display():
    seen: list[str] = []
    show_start_failure("bind failed", display=seen.append)
    assert seen == ["bind failed"]


def test_support_logging_writes_under_console_data_directory(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        log_path = configure_support_logging(tmp_path)
        assert log_path == tmp_path / "logs" / "process-host.log"
        assert log_path.is_file()
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_windows_restore_syscommand_is_not_close():
    assert _sys_command(SC_RESTORE) == SC_RESTORE
    assert _sys_command(SC_RESTORE | 0x0002) == SC_RESTORE


def test_reopen_browser_opens_bound_port():
    session = ProcessHostSession(port=8122, server=None, stop_event=threading.Event())
    with patch("server.process_host.runtime.open_spa") as mock_open:
        session.reopen_browser()
    mock_open.assert_called_once_with(8122)
