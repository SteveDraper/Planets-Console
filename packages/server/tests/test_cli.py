"""Unit tests for the serve CLI and --config option."""

from __future__ import annotations

from unittest.mock import patch

from api.config import ApiConfig
from bff.config import BffConfig
from server.cli import app
from server.config import RootConfig, ServerConfig
from typer.testing import CliRunner

runner = CliRunner()


def test_serve_help_includes_config_option():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--config" in result.output or "-c" in result.output
    assert "key.leaf=value" in result.output or "Override" in result.output


def test_serve_config_prints_documentation():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Configuration" in result.output
    assert "Override syntax" in result.output
    assert "server.host" in result.output
    assert "server.port" in result.output


def test_serve_calls_load_config_with_config_args():
    fake_root = RootConfig(
        server=ServerConfig(host="127.0.0.1", port=8000),
        api=ApiConfig(),
        bff=BffConfig(),
    )
    with (
        patch("server.cli.load_config", return_value=fake_root) as mock_load,
        patch("uvicorn.run") as mock_uvicorn,
    ):
        result = runner.invoke(app, ["--config", "server.port=9000"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kw = mock_load.call_args[1]
    assert "override_specs" in call_kw
    assert call_kw["override_specs"] == ["server.port=9000"]
    mock_uvicorn.assert_called_once()
    assert mock_uvicorn.call_args[1]["port"] == 8000  # from fake_root


def test_serve_passes_loaded_host_port_to_uvicorn():
    fake_root = RootConfig(
        server=ServerConfig(host="0.0.0.0", port=9000),
        api=ApiConfig(),
        bff=BffConfig(),
    )
    with (
        patch("server.cli.load_config", return_value=fake_root),
        patch("uvicorn.run") as mock_uvicorn,
    ):
        runner.invoke(app, [])
    assert mock_uvicorn.call_args[1]["host"] == "0.0.0.0"
    assert mock_uvicorn.call_args[1]["port"] == 9000


def test_serve_config_subcommand_help():
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "config" in result.output.lower()
