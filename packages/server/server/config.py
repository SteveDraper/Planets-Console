"""Amalgamated config loading with default .config.yaml and --config overrides."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.config import ApiConfig
from bff.config import BffConfig
from omegaconf import OmegaConf

DEFAULT_CONFIG_FILENAME = ".config.yaml"


@dataclass
class ServerConfig:
    """Server process: bind host and port."""

    host: str = "127.0.0.1"
    port: int = 8000


@dataclass
class RootConfig:
    """Amalgamated config: server, api, and bff sub-configs."""

    server: ServerConfig
    api: ApiConfig
    bff: BffConfig


def _find_default_config() -> Path | None:
    """Search cwd and parents for .config.yaml."""
    p = Path.cwd()
    for _ in range(10):
        candidate = p / DEFAULT_CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None


def _parse_literal(value: str) -> str | int | float | bool:
    """Parse a literal value: int, float, bool, or string."""
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_override_spec(spec: str) -> tuple[str, str | tuple[str, str]]:
    """
    Parse one --config spec. Returns (key, value).
    - '@path' -> ('@', path)  full config replacement
    - 'key.path.leaf=literal' -> ('key.path.leaf', literal)
    - 'key.path=@path' -> ('key.path', ('@', path))  substructure from file
    """
    spec = spec.strip()
    if spec.startswith("@"):
        return ("@", spec[1:].strip())
    if "=" not in spec:
        raise ValueError(f"Invalid --config spec (expected key=value or key=@file): {spec!r}")
    key, _, value = spec.partition("=")
    key = key.strip().rstrip(".")
    value = value.strip()
    if value.startswith("@"):
        return (key, ("@", value[1:].strip()))
    return (key, value)


def _apply_override(conf: Any, key: str, value: str | tuple[str, str]) -> None:
    """Apply one override to OmegaConf. conf is modified in place."""
    if key == "@":
        raise ValueError("Full config replace (@file) must be applied separately")
    if isinstance(value, tuple):
        # key=@file: load file and set substructure
        _, path = value
        sub = OmegaConf.load(path)
        OmegaConf.update(conf, key, sub, merge=True)
    else:
        # leaf=literal: spec allows only leaf overrides
        existing = OmegaConf.select(conf, key, default=None)
        if existing is not None and (OmegaConf.is_config(existing) or OmegaConf.is_list(existing)):
            raise ValueError(
                f"Override {key}=<value> is for leaf values only; {key} is a nested "
                "structure (use key=@file to replace)"
            )
        OmegaConf.update(conf, key, _parse_literal(value), merge=False)


def load_config(
    override_specs: list[str] | None = None,
    *,
    default_config_path: Path | None = None,
) -> RootConfig:
    """
    Load amalgamated config: default .config.yaml plus optional overrides.

    override_specs: list of strings from --config
        (e.g. ['api.storage_backend=file', 'bff=@bff.yaml']).
    default_config_path: if set, use this as base instead of searching for .config.yaml.
    """
    override_specs = override_specs or []
    # Resolve full-file replacements first (last @file wins)
    full_replace_path: str | None = None
    other_overrides: list[tuple[str, str | tuple[str, str]]] = []
    for spec in override_specs:
        key, value = _parse_override_spec(spec)
        if key == "@":
            full_replace_path = value  # always str for "@path" spec
        else:
            other_overrides.append((key, value))

    # Base config
    if full_replace_path is not None:
        conf = OmegaConf.load(full_replace_path)
    elif default_config_path is not None and default_config_path.is_file():
        conf = OmegaConf.load(default_config_path)
    else:
        found = _find_default_config()
        if found is not None:
            conf = OmegaConf.load(found)
        else:
            conf = OmegaConf.create({"server": {}, "api": {}, "bff": {}})

    # Ensure server, api, and bff exist
    if "server" not in conf:
        OmegaConf.update(conf, "server", {}, merge=True)
    if "api" not in conf:
        OmegaConf.update(conf, "api", {}, merge=True)
    if "bff" not in conf:
        OmegaConf.update(conf, "bff", {}, merge=True)

    # Apply overrides in order
    for key, value in other_overrides:
        if isinstance(value, tuple):
            _apply_override(conf, key, value)
        else:
            # Leaf override: validate we're not setting a non-leaf
            # (OmegaConf allows it but spec says leaf only)
            _apply_override(conf, key, value)

    # Convert to RootConfig with typed sub-configs
    server_dict = OmegaConf.to_container(conf.server, resolve=True) or {}
    api_dict = OmegaConf.to_container(conf.api, resolve=True) or {}
    bff_dict = OmegaConf.to_container(conf.bff, resolve=True) or {}
    server_config = ServerConfig(
        host=str(server_dict.get("host", ServerConfig().host)),
        port=int(server_dict.get("port", ServerConfig().port)),
    )
    include_dummy = api_dict.get("include_dummy_data", ApiConfig().include_dummy_data)
    if not isinstance(include_dummy, bool):
        raise TypeError(
            f"api.include_dummy_data must be a boolean, got "
            f"{type(include_dummy).__name__}: {include_dummy!r}"
        )
    api_config = ApiConfig(
        storage_backend=str(api_dict.get("storage_backend", ApiConfig().storage_backend)),
        storage_asset_path=api_dict.get("storage_asset_path"),
        include_dummy_data=include_dummy,
        planets_api_base_url=str(
            api_dict.get("planets_api_base_url", ApiConfig().planets_api_base_url)
        ),
    )
    cors = bff_dict.get("cors_origins")
    if isinstance(cors, list):
        cors_tuple = tuple(str(o) for o in cors)
    else:
        cors_tuple = getattr(
            BffConfig(),
            "cors_origins",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        )
    raw_show = bff_dict.get("show_initial_game")
    if raw_show is None:
        show_initial_game: str | None = None
    elif isinstance(raw_show, bool):
        raise TypeError(
            f"bff.show_initial_game must be a string or null, got boolean: {raw_show!r}"
        )
    elif isinstance(raw_show, int):
        show_initial_game = str(raw_show)
    elif isinstance(raw_show, str):
        stripped = raw_show.strip()
        show_initial_game = stripped if stripped else None
    else:
        raise TypeError(
            f"bff.show_initial_game must be a string, int, or null, got "
            f"{type(raw_show).__name__}: {raw_show!r}"
        )
    raw_db = bff_dict.get("diagnostics_buffer_size", BffConfig().diagnostics_buffer_size)
    if isinstance(raw_db, bool):
        raise TypeError(
            f"bff.diagnostics_buffer_size must be an int, got {type(raw_db).__name__}: {raw_db!r}"
        )
    if isinstance(raw_db, float) and raw_db.is_integer():
        raw_db = int(raw_db)
    if not isinstance(raw_db, int):
        raise TypeError(
            f"bff.diagnostics_buffer_size must be an int, got {type(raw_db).__name__}: {raw_db!r}"
        )
    if raw_db < 0:
        raise ValueError(f"bff.diagnostics_buffer_size must be >= 0, got {raw_db}")
    raw_live = bff_dict.get(
        "connection_routes_live_compare", BffConfig().connection_routes_live_compare
    )
    if not isinstance(raw_live, bool):
        raise TypeError(
            f"bff.connection_routes_live_compare must be a bool, got "
            f"{type(raw_live).__name__}: {raw_live!r}"
        )
    bff_config = BffConfig(
        cors_origins=cors_tuple,
        show_initial_game=show_initial_game,
        diagnostics_buffer_size=raw_db,
        connection_routes_live_compare=raw_live,
    )
    return RootConfig(server=server_config, api=api_config, bff=bff_config)
