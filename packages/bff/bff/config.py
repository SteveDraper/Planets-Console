"""BFF sub-config: SPA-shaped endpoint behaviour. Set by server from amalgamated config."""

from dataclasses import dataclass

_config: "BffConfig | None" = None


@dataclass(frozen=True)
class BffConfig:
    """Configuration for the BFF layer."""

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    """Allowed CORS origins for the SPA."""
    show_initial_game: str | None = None
    """When set, the SPA loads this stored game id from the server without login (dev/demo)."""
    diagnostics_buffer_size: int = 10
    """How many most-recent per-request diagnostic trees to keep (0 disables retention)."""
    connection_routes_live_compare: bool = False
    """If True, BFF ``/analytics/connections/map`` runs both route algorithms, illustrative
    validation, full diff, and (when includeDiagnostics) a diagnostic child — intended for local
    verification, not for production default traffic."""


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
    from bff.diagnostics_buffer import reconfigure_diagnostics_buffer

    reconfigure_diagnostics_buffer(cfg.diagnostics_buffer_size)
