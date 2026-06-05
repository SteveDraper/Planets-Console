#!/usr/bin/env python3
"""Run or discover inference corpus cases from stored finished-game turns."""

from __future__ import annotations

import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

import typer  # noqa: E402
from api.services.store_service import StoreService  # noqa: E402
from tests.inference_corpus.complexity import parse_max_complexity  # noqa: E402
from tests.inference_corpus.discover_list import (  # noqa: E402
    discover_case_listings,
    format_listing_report,
)
from tests.inference_corpus.report import report_to_json, run_local_corpus  # noqa: E402
from tests.inference_corpus.storage_loader import (  # noqa: E402
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)

app = typer.Typer(
    add_completion=False,
    help="Discover and run inference corpus cases from stored finished-game turns.",
)


def _default_storage_root() -> Path:
    return Path(".data")


def _configure_services(storage_root: Path):
    if not storage_root.is_dir():
        typer.echo(f"storage root not found: {storage_root}", err=True)
        raise typer.Exit(code=2)
    storage = configure_file_storage(storage_root=storage_root)
    return (
        storage,
        make_turn_load_service(storage),
        make_game_service(storage),
        StoreService(storage),
    )


def _warn_missing_game_info(storage_root: Path, game_id: int) -> None:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    if not info_path.is_file():
        typer.echo(
            f"warning: missing game info at {info_path}; player resolution may fail",
            err=True,
        )


@app.callback(invoke_without_command=True)
def run_command(
    ctx: typer.Context,
    game_id: int | None = typer.Option(
        None,
        "--game-id",
        help="Finished game id to scan. Omit to scan every game under storage.",
    ),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root (default: ./.data).",
    ),
    from_turn: int | None = typer.Option(
        None,
        "--from-turn",
        help="Minimum host turn N to include (inclusive).",
    ),
    to_turn: int | None = typer.Option(
        None,
        "--to-turn",
        help="Maximum host turn N to include (inclusive).",
    ),
    max_complexity: str = typer.Option(
        "heavy",
        "--max-complexity",
        help="Skip cases above this level: minimal, routine, heavy, adjunct, or 0-3.",
    ),
    include_adjunct: bool = typer.Option(
        False,
        "--include-adjunct",
        help="Run adjunct cases instead of skipping them.",
    ),
    top_k: int = typer.Option(
        3,
        "--top-k",
        help="Reserved for ground-truth ranking checks (#65); accepted for CLI stability.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print per-case JSON records instead of a text summary.",
    ),
) -> None:
    """Discover host-turn pairs in storage and run Tier 1 inference checks."""
    if ctx.invoked_subcommand is not None:
        return

    del top_k  # wired in #65

    try:
        complexity_cap = parse_max_complexity(max_complexity)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    storage, turn_load, game_service, store = _configure_services(storage_root)

    if game_id is not None:
        _warn_missing_game_info(storage_root, game_id)

    report = run_local_corpus(
        store=store,
        turn_load=turn_load,
        game_service=game_service,
        game_id=game_id,
        min_host_turn=from_turn,
        max_host_turn=to_turn,
        max_complexity=complexity_cap,
        include_adjunct=include_adjunct,
    )

    if json_output:
        typer.echo(report_to_json(report))
    else:
        for line in report.summary_lines():
            typer.echo(line)

    raise typer.Exit(code=report.exit_code)


@app.command("discover")
def discover_command(
    game_id: int = typer.Option(..., "--game-id", help="Finished game id to scan."),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root (default: ./.data).",
    ),
    from_turn: int | None = typer.Option(
        None,
        "--from-turn",
        help="Minimum host turn N to include (inclusive).",
    ),
    to_turn: int | None = typer.Option(
        None,
        "--to-turn",
        help="Maximum host turn N to include (inclusive).",
    ),
) -> None:
    """List discovered cases with human-readable ground-truth build summaries."""
    storage, turn_load, game_service, store = _configure_services(storage_root)
    _warn_missing_game_info(storage_root, game_id)

    listings = discover_case_listings(
        store=store,
        turn_load=turn_load,
        game_service=game_service,
        game_id=game_id,
        min_host_turn=from_turn,
        max_host_turn=to_turn,
    )

    for line in format_listing_report(listings, game_id=game_id):
        typer.echo(line)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
