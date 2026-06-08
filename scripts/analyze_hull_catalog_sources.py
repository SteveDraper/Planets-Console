#!/usr/bin/env python3
"""Analyze buildable hull catalog heuristics against per-perspective ground truth."""

from __future__ import annotations

import json
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
from hull_catalog_analysis import (  # noqa: E402
    analysis_to_json,
    analyze_game,
    format_text_report,
    hull_names_from_turn,
    load_game_info,
    load_turn_file,
)

app = typer.Typer(
    add_completion=False,
    help="Compare hull catalog heuristics to per-perspective turn.racehulls ground truth.",
)

DEFAULT_GAME_IDS = (628580, 673864)


def _default_storage_root() -> Path:
    return Path(".data")


@app.callback(invoke_without_command=True)
def run_command(
    ctx: typer.Context,
    game_id: list[int] = typer.Option(
        [],
        "--game-id",
        help="Game id to analyze (repeatable). Defaults to 628580 and 673864 when omitted.",
    ),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root (default: ./.data).",
    ),
    turn: int | None = typer.Option(
        None,
        "--turn",
        help="Host turn to analyze. Defaults to each game's current turn from info.json.",
    ),
    loaded_perspective: int = typer.Option(
        1,
        "--loaded-perspective",
        help="Perspective slot used as the single loaded turn snapshot.",
    ),
    compare_turn: int | None = typer.Option(
        None,
        "--compare-turn",
        help="Optional second turn to check ground-truth stability across turns.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print JSON report instead of human-readable text.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Write report to this file (JSON when --json, else plain text).",
    ),
) -> None:
    """Run hull catalog analysis for one or more stored games."""
    if ctx.invoked_subcommand is not None:
        return

    if not storage_root.is_dir():
        typer.echo(f"storage root not found: {storage_root}", err=True)
        raise typer.Exit(code=2)

    selected_game_ids = game_id or list(DEFAULT_GAME_IDS)
    reports: list[dict[str, object]] = []
    text_blocks: list[str] = []

    for selected_game_id in selected_game_ids:
        try:
            game_info, settings_defaults = load_game_info(storage_root, selected_game_id)
        except FileNotFoundError:
            typer.echo(f"warning: missing info.json for game {selected_game_id}", err=True)
            continue

        host_turn = turn if turn is not None else game_info.settings.turn
        try:
            analysis = analyze_game(
                storage_root,
                selected_game_id,
                host_turn=host_turn,
                loaded_perspective=loaded_perspective,
                settings_defaults=settings_defaults,
                game_info=game_info,
                compare_turn=compare_turn,
            )
        except FileNotFoundError as exc:
            typer.echo(f"warning: {exc}", err=True)
            continue

        loaded_turn = load_turn_file(
            storage_root,
            selected_game_id,
            loaded_perspective,
            host_turn,
            settings_defaults=settings_defaults,
        )
        if loaded_turn is None:
            typer.echo(
                f"warning: could not reload turn for game {selected_game_id}",
                err=True,
            )
            continue

        hull_names = hull_names_from_turn(loaded_turn)
        hulls_by_id = {hull.id: hull for hull in loaded_turn.hulls}
        reports.append(analysis_to_json(analysis, hull_names))
        text_blocks.append(
            "\n".join(format_text_report(analysis, hull_names, hulls_by_id=hulls_by_id))
        )

    if not reports:
        typer.echo("no games analyzed", err=True)
        raise typer.Exit(code=2)

    if json_output:
        payload = {"games": reports}
        rendered = json.dumps(payload, indent=2)
        if output is not None:
            output.write_text(rendered + "\n", encoding="utf-8")
        else:
            typer.echo(rendered)
    else:
        rendered = "\n\n".join(text_blocks)
        if output is not None:
            output.write_text(rendered + "\n", encoding="utf-8")
        else:
            typer.echo(rendered)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
