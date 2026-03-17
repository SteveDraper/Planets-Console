"""BFF sub-config: SPA-shaped endpoint behaviour. Set by server from amalgamated config."""

from dataclasses import dataclass

_config: "BffConfig | None" = None


@dataclass(frozen=True)
class BffConfig:
    """Configuration for the BFF layer."""

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    """Allowed CORS origins for the SPA."""


def get_config() -> BffConfig:
    """Return the current BFF config. Defaults if not yet set by server."""
    global _config
    if _config is None:
        _config = BffConfig()
    return _config


def set_config(cfg: BffConfig) -> None:
    """Set the BFF config (called by server at startup)."""
    global _config
    _config = cfg
