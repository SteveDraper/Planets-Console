"""Unit tests for amalgamated config loading and override parsing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from omegaconf import OmegaConf

from server.config import (
    DEFAULT_CONFIG_FILENAME,
    RootConfig,
    ServerConfig,
    _apply_override,
    _find_default_config,
    _parse_literal,
    _parse_override_spec,
    load_config,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---- _parse_override_spec ----
def test_parse_override_spec_full_replace():
    key, value = _parse_override_spec("@/etc/app.yaml")
    assert key == "@"
    assert value == "/etc/app.yaml"


def test_parse_override_spec_full_replace_stripped():
    key, value = _parse_override_spec("  @ ./local.yaml  ")
    assert key == "@"
    assert value == "./local.yaml"


def test_parse_override_spec_leaf_literal():
    key, value = _parse_override_spec("server.port=9000")
    assert key == "server.port"
    assert value == "9000"


def test_parse_override_spec_leaf_with_dots():
    key, value = _parse_override_spec("api.storage_asset_path=/data/store.json")
    assert key == "api.storage_asset_path"
    assert value == "/data/store.json"


def test_parse_override_spec_substructure_from_file():
    key, value = _parse_override_spec("bff=@bff-override.yaml")
    assert key == "bff"
    assert isinstance(value, tuple)
    assert value[0] == "@"
    assert value[1] == "bff-override.yaml"


def test_parse_override_spec_invalid_no_equals():
    with pytest.raises(ValueError, match="Invalid --config spec"):
        _parse_override_spec("noequals")


# ---- _parse_literal ----
def test_parse_literal_bool_true():
    assert _parse_literal("true") is True
    assert _parse_literal("yes") is True


def test_parse_literal_bool_false():
    assert _parse_literal("false") is False
    assert _parse_literal("no") is False


def test_parse_literal_int():
    assert _parse_literal("42") == 42
    assert _parse_literal("0") == 0


def test_parse_literal_float():
    assert _parse_literal("3.14") == 3.14


def test_parse_literal_string():
    assert _parse_literal("hello") == "hello"
    assert _parse_literal("/path/to/file") == "/path/to/file"


# ---- _apply_override ----
def test_apply_override_leaf_literal():
    conf = OmegaConf.create({"server": {"port": 8000}})
    _apply_override(conf, "server.port", "9000")
    assert OmegaConf.to_container(conf, resolve=True)["server"]["port"] == 9000


def test_apply_override_leaf_on_nested_raises():
    conf = OmegaConf.create({"api": {"storage_backend": "ephemeral"}})
    with pytest.raises(ValueError, match="leaf values only"):
        _apply_override(conf, "api", "other")


def test_apply_override_full_replace_key_raises():
    conf = OmegaConf.create({"server": {}})
    with pytest.raises(ValueError, match="Full config replace"):
        _apply_override(conf, "@", "/path")


def test_apply_override_substructure_from_file():
    conf = OmegaConf.create({"bff": {"cors_origins": ["old"]}})
    bff_file = FIXTURES_DIR / "bff_section.yaml"
    _apply_override(conf, "bff", ("@", str(bff_file)))
    bff = OmegaConf.to_container(conf.bff, resolve=True)
    assert "https://custom.example.com" in bff["cors_origins"]
    assert "http://localhost:3000" in bff["cors_origins"]


# ---- load_config ----
def test_load_config_with_default_config_path():
    base = FIXTURES_DIR / "base.yaml"
    root = load_config(default_config_path=base)
    assert root.server.host == "127.0.0.1"
    assert root.server.port == 8000
    assert root.api.storage_backend == "ephemeral"
    assert root.api.storage_asset_path is None
    assert "http://localhost:5173" in root.bff.cors_origins


def test_load_config_leaf_overrides():
    base = FIXTURES_DIR / "base.yaml"
    root = load_config(
        override_specs=["server.port=9000", "server.host=0.0.0.0"],
        default_config_path=base,
    )
    assert root.server.port == 9000
    assert root.server.host == "0.0.0.0"


def test_load_config_leaf_override_api():
    base = FIXTURES_DIR / "base.yaml"
    root = load_config(
        override_specs=["api.storage_asset_path=/var/data/store.json"],
        default_config_path=base,
    )
    assert root.api.storage_asset_path == "/var/data/store.json"


def test_load_config_full_replace():
    full_path = FIXTURES_DIR / "full_replace.yaml"
    root = load_config(override_specs=[f"@{full_path}"])
    assert root.server.host == "0.0.0.0"
    assert root.server.port == 9000
    assert root.api.storage_asset_path == "/var/data/store.json"
    assert root.bff.cors_origins == ("https://app.example.com",)


def test_load_config_substructure_from_file():
    base = FIXTURES_DIR / "base.yaml"
    bff_file = FIXTURES_DIR / "bff_section.yaml"
    root = load_config(
        override_specs=[f"bff=@{bff_file}"],
        default_config_path=base,
    )
    assert "https://custom.example.com" in root.bff.cors_origins
    assert "http://localhost:3000" in root.bff.cors_origins


def test_load_config_no_file_uses_internal_defaults():
    with patch("server.config._find_default_config", return_value=None):
        root = load_config(
            override_specs=[],
            default_config_path=Path("/nonexistent"),
        )
    assert root.server.host == "127.0.0.1"
    assert root.server.port == 8000
    assert root.api.storage_backend == "ephemeral"
    assert root.api.storage_asset_path is None
    assert "http://localhost:5173" in root.bff.cors_origins


def test_load_config_later_override_wins():
    base = FIXTURES_DIR / "base.yaml"
    root = load_config(
        override_specs=["server.port=9000", "server.port=8001"],
        default_config_path=base,
    )
    assert root.server.port == 8001


def test_load_config_full_replace_last_wins():
    base = FIXTURES_DIR / "base.yaml"
    full_path = FIXTURES_DIR / "full_replace.yaml"
    root = load_config(
        override_specs=[f"@{base}", f"@{full_path}"],
    )
    assert root.server.port == 9000
    assert root.server.host == "0.0.0.0"


def test_load_config_include_dummy_data_bool():
    base = FIXTURES_DIR / "base.yaml"
    root = load_config(
        override_specs=["api.include_dummy_data=true"],
        default_config_path=base,
    )
    assert root.api.include_dummy_data is True


def test_load_config_include_dummy_data_string_raises():
    """A string like 'false' must not silently coerce to True via bool()."""
    base = FIXTURES_DIR / "base.yaml"
    with pytest.raises(TypeError, match="must be a boolean"):
        load_config(
            override_specs=["api.include_dummy_data=notabool"],
            default_config_path=base,
        )
