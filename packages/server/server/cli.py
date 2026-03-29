"""Typer CLI to run the server locally."""

import typer
import uvicorn
from api import config as api_config
from bff import config as bff_config

from server.config import load_config

app = typer.Typer()

CONFIG_OPTION_HELP = (
    "Override config (repeatable). Forms: key.leaf=value, key=@file, or @file for "
    "full config. Base: .config.yaml. See 'serve config' for details."
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    reload: bool = typer.Option(False, help="Enable reload"),
    config: list[str] = typer.Option(
        [],
        "--config",
        "-c",
        help=CONFIG_OPTION_HELP,
    ),
):
    """Run the Planets Console server (API + BFF)."""
    if ctx.invoked_subcommand is not None:
        return
    root = load_config(override_specs=config if config else None)
    api_config.set_config(root.api)
    bff_config.set_config(root.bff)
    uvicorn.run(
        "server.app:app",
        host=root.server.host,
        port=root.server.port,
        reload=reload,
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
  api.storage_backend     string   [default: ephemeral]  Backend ID
  api.storage_asset_path  string or null  [default: null]   JSON for store; null = empty
  api.include_dummy_data  bool     [default: false]  Seed sample game data on startup
  bff.cors_origins        list of strings  CORS origins for the SPA
  bff.show_initial_game   string or null [default: null]  SPA loads this game without login

See docs/configuration.md for full documentation.
"""


app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
