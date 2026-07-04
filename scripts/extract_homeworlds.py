#!/usr/bin/env python3
"""Extract homeworld coordinates from stored games and write a CSV report."""

from __future__ import annotations

import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
_api_root_str = str(_API_ROOT)
if _api_root_str in sys.path:
    sys.path.remove(_api_root_str)
sys.path.insert(0, _api_root_str)

_SCRIPTS_ROOT = Path(__file__).resolve().parent
_scripts_root_str = str(_SCRIPTS_ROOT)
if _scripts_root_str not in sys.path:
    sys.path.insert(0, _scripts_root_str)

import typer  # noqa: E402
from api.concepts.game_category import GameCategory  # noqa: E402
from homeworld_extraction import (  # noqa: E402
    extract_homeworlds_by_category,
    flatten_homeworld_rows,
    write_homeworld_csv,
)

app = typer.Typer(
    add_completion=False,
    help=(
        "Scan a file storage root (e.g. .sampler_data or .data), classify games, "
        "and export turn-1 homeworld coordinates for epic and standard games."
    ),
)


def _default_storage_root() -> Path:
    return Path(".data")


@app.callback(invoke_without_command=True)
def run_command(
    ctx: typer.Context,
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root containing games/{id}/... (default: ./.data).",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="CSV file to write (columns: game_type, game_id, player, x, y).",
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    if not storage_root.is_dir():
        typer.echo(f"storage root not found: {storage_root}", err=True)
        raise typer.Exit(code=2)

    grouped = extract_homeworlds_by_category(storage_root)
    rows = flatten_homeworld_rows(grouped)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        write_homeworld_csv(rows, handle)

    epic_count = len(grouped[GameCategory.EPIC])
    standard_count = len(grouped[GameCategory.STANDARD])
    typer.echo(
        f"wrote {len(rows)} homeworld row(s) from "
        f"{epic_count} epic and {standard_count} standard game(s) to {output}"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
