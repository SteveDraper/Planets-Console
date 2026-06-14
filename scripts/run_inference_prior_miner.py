#!/usr/bin/env python3
"""Run the inference prior miner against finished Planets.nu games."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
_api_root_str = str(_API_ROOT)
if _api_root_str in sys.path:
    sys.path.remove(_api_root_str)
sys.path.insert(0, _api_root_str)

import typer  # noqa: E402
from api.analytics.military_score_inference.prior_mining.runner import (  # noqa: E402
    default_assets_dir,
    run_prior_miner,
)
from api.planets_nu import PlanetsNuClient  # noqa: E402
from api.transport.game_info_update import RefreshGameInfoParams  # noqa: E402
from tests.inference_corpus.storage_loader import (  # noqa: E402
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)

app = typer.Typer(
    add_completion=False,
    help="Discover finished games and mine inference build priors (#92).",
)


def _default_storage_root() -> Path:
    return Path(".data")


@app.callback(invoke_without_command=True)
def run_command(
    ctx: typer.Context,
    patterns: Path = typer.Option(
        ...,
        "--patterns",
        help="Path to a prior mining patterns YAML file (required).",
    ),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root for turn storage (default: ./.data).",
    ),
    assets_dir: Path | None = typer.Option(
        None,
        "--assets-dir",
        help="Directory containing prior_weights_{category}.yaml (default: repo assets).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Discover and report tallies without writing prior weight assets.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help=(
            "Count rejected games toward pattern max_games "
            "(stop after N attempts, not N successes)."
        ),
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        min=1,
        help="Parallel extraction worker processes (default: 1).",
    ),
    username: str = typer.Option(
        "",
        "--username",
        help="Planets.nu login for fetching final turns after loadall import.",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Planets.nu password for final-turn fetch (optional if API key is cached).",
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report",
        help="Optional path to write the JSON miner report.",
    ),
) -> None:
    """Discover games from patterns, import turns, and merge prior weights."""
    if ctx.invoked_subcommand is not None:
        return

    if not patterns.is_file():
        typer.echo(f"patterns file not found: {patterns}", err=True)
        raise typer.Exit(code=2)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    storage = configure_file_storage(storage_root=storage_root)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    planets = PlanetsNuClient.from_config()
    resolved_assets_dir = default_assets_dir() if assets_dir is None else assets_dir
    loadall_params = (
        RefreshGameInfoParams(username=username, password=password) if username.strip() else None
    )

    mining_report = run_prior_miner(
        patterns_path=patterns,
        storage_root=storage_root,
        assets_dir=resolved_assets_dir,
        planets=planets,
        turn_load=turn_load,
        game_service=game_service,
        storage=storage,
        dry_run=dry_run,
        debug=debug,
        workers=workers,
        loadall_params=loadall_params,
    )

    report_json = mining_report.to_json()
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_json, encoding="utf-8")
        typer.echo(f"wrote full report to {report_path}", err=True)
    typer.echo(mining_report.to_summary_json())

    if mining_report.written_assets:
        typer.echo(f"wrote {len(mining_report.written_assets)} asset(s)", err=True)

    if mining_report.aborted:
        typer.echo(
            f"prior miner aborted before completing all patterns: {mining_report.abort_message}",
            err=True,
        )
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
