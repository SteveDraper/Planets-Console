"""Typer CLI to run the server locally."""

import typer
import uvicorn
from api import config as api_config
from bff import config as bff_config

from server.config import load_config, load_packaged_config

app = typer.Typer()

# All `serve` invocations (dev and deploy via scripts/run_deploy.sh): bound
# graceful shutdown so SIGTERM does not wait forever on NDJSON/MCP streams.
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5.0

CONFIG_OPTION_HELP = (
    "Override config (repeatable). Forms: key.leaf=value, key=@file, or @file for "
    "full config. Base: .config.yaml unless --packaged. See 'serve config' for details."
)

PACKAGED_OPTION_HELP = (
    "Packaged console launch: file backend at the OS console data directory; "
    "skip .config.yaml discovery. Extra --config specs still apply (later wins)."
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    reload: bool = typer.Option(False, help="Enable reload"),
    packaged: bool = typer.Option(False, "--packaged", help=PACKAGED_OPTION_HELP),
    config: list[str] = typer.Option(
        [],
        "--config",
        "-c",
        help=CONFIG_OPTION_HELP,
    ),
):
    """Run the Planets Console server (API + BFF + MCP)."""
    if ctx.invoked_subcommand is not None:
        return
    override_specs = config if config else None
    if packaged:
        root = load_packaged_config(override_specs=override_specs)
    else:
        root = load_config(override_specs=override_specs)
    api_config.set_config(root.api)
    bff_config.set_config(root.bff)
    uvicorn.run(
        "server.app:create_app",
        host=root.server.host,
        port=root.server.port,
        reload=reload,
        factory=True,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    )


config_app = typer.Typer(help="Show configuration options and override syntax.")


@config_app.callback(invoke_without_command=True)
def config_help(ctx: typer.Context) -> None:
    """Print config structure and --config override syntax. Use with --help to see this."""
    if ctx.invoked_subcommand is not None:
        return
    print(CONFIG_HELP_TEXT)


CONFIG_HELP_TEXT = """
Configuration (amalgamated server + api + bff)
==============================================
Base file: .config.yaml (searched from cwd upward). Override with -c/--config.
--packaged skips that search and uses the OS console data directory as the
file-backend root. Extra --config specs still apply (later wins).

Override syntax (can be repeated):
  1. Leaf:       --config key.path.leaf=<value>
                 Example: -c server.port=9000
  2. From file:  --config key.path=@filepath
                 Example: -c bff=@bff-override.yaml
  3. Full:       --config @filepath
                 Example: -c @production.yaml (or any path)

Config structure:
  server.host             string   [default: 127.0.0.1]  Bind host
  server.port             int      [default: 8000]     Bind port
  api.storage_backend     string   [default: ephemeral]  Backend ID (ephemeral | file)
  api.storage_root        string   [default: ./.data]    File backend root directory
  api.storage_asset_path  string or null  [default: null]   Ephemeral JSON seed; null = empty
  api.include_dummy_data  bool     [default: false]  Seed sample game data on startup
  bff.cors_origins        list of strings  CORS origins for the SPA
  bff.show_initial_game   string or null [default: null]  SPA loads this game without login

See docs/configuration.md for full documentation.
"""


app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
