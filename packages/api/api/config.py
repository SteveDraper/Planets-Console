"""Core API sub-config: storage and API behaviour. Set by server from amalgamated config."""
from dataclasses import dataclass

_config: "ApiConfig | None" = None


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the Core REST API layer."""

    storage_backend: str = "ephemeral"
    """Backend key: 'ephemeral' (asset-backed in-memory)."""

    storage_asset_path: str | None = None
    """Optional path to JSON asset for ephemeral backend. If unset, store starts empty."""

    include_dummy_data: bool = False
    """Seed the store with sample game data on startup. For development/testing only."""


def get_config() -> ApiConfig:
    """Return the current API config. Defaults if not yet set by server."""
    global _config
    if _config is None:
        _config = ApiConfig()
    return _config


def set_config(cfg: ApiConfig) -> None:
    """Set the API config (called by server at startup)."""
    global _config
    _config = cfg
