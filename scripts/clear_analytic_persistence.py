#!/usr/bin/env python3
"""Clear persisted analytic state for a game, with optional perspective/player wildcards.

Removes turn-scoped and perspective-scoped analytic documents under file storage, and
game-global per-player hull catalog masks. Use ``*`` for ``--perspective`` or
``--player`` to match all values for that axis independently.

Examples::

    uv run python scripts/clear_analytic_persistence.py \\
        --game-id 628580 --perspective 11 --player '*'
    uv run python scripts/clear_analytic_persistence.py \\
        --game-id 628580 --perspective '*' --player 8
    uv run python scripts/clear_analytic_persistence.py \\
        --game-id 628580 --perspective '*' --player '*'
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
_api_root_str = str(_API_ROOT)
if _api_root_str in sys.path:
    sys.path.remove(_api_root_str)
sys.path.insert(0, _api_root_str)

import typer  # noqa: E402
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID  # noqa: E402
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService  # noqa: E402
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID  # noqa: E402
from api.errors import NotFoundError  # noqa: E402
from api.services.inference_row_persistence_service import (  # noqa: E402
    InferenceRowPersistenceService,
)
from api.storage.base import StorageBackend  # noqa: E402
from api.storage.file import FileStorageBackend  # noqa: E402

WILDCARD = "*"
_HULL_MASKS_KEY = "inference_hull_catalog_masks"
_INFERENCE_ROWS_KEY = "inference_rows"

app = typer.Typer(
    add_completion=False,
    help=(
        "Clear persisted analytic state for a game. "
        "Perspective and player may each be a number or '*'."
    ),
)


@dataclass(frozen=True)
class ClearAnalyticPersistenceResult:
    """Paths / entries removed (or that would be removed under dry-run)."""

    deleted_documents: list[str] = field(default_factory=list)
    deleted_player_entries: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.deleted_documents) + len(self.deleted_player_entries)


def parse_selector(raw: str, *, label: str) -> int | None:
    """Return an int selector, or ``None`` for wildcard ``*``."""
    value = raw.strip()
    if value == WILDCARD:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer or '*', got {raw!r}") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be >= 0, got {parsed}")
    return parsed


def _list_segments(storage: StorageBackend, prefix: str) -> list[str]:
    try:
        return list(storage.list(prefix))
    except NotFoundError:
        return []


def _list_int_segments(storage: StorageBackend, prefix: str) -> list[int]:
    values: list[int] = []
    for segment in _list_segments(storage, prefix):
        if segment.isdigit():
            values.append(int(segment))
    return sorted(values)


def _resolve_perspectives(
    storage: StorageBackend,
    game_id: int,
    perspective: int | None,
) -> list[int]:
    if perspective is not None:
        return [perspective]
    return _list_int_segments(storage, f"games/{game_id}")


def _delete_document(
    storage: StorageBackend,
    key: str,
    *,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    if dry_run:
        try:
            storage.get(key)
        except NotFoundError:
            return
        result.deleted_documents.append(key)
        return
    try:
        storage.delete(key)
    except NotFoundError:
        return
    result.deleted_documents.append(key)


def _delete_player_entry(
    storage: StorageBackend,
    key: str,
    *,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    if dry_run:
        try:
            storage.get(key)
        except NotFoundError:
            return
        result.deleted_player_entries.append(key)
        return
    try:
        storage.delete(key)
    except NotFoundError:
        return
    result.deleted_player_entries.append(key)


def _clear_turn_analytics_for_all_players(
    storage: StorageBackend,
    *,
    game_id: int,
    perspective: int,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    turns_prefix = f"games/{game_id}/{perspective}/turns"
    for turn_number in _list_int_segments(storage, turns_prefix):
        analytics_prefix = f"{turns_prefix}/{turn_number}/analytics"
        for analytic_id in sorted(_list_segments(storage, analytics_prefix)):
            _delete_document(
                storage,
                f"{analytics_prefix}/{analytic_id}",
                dry_run=dry_run,
                result=result,
            )


def _clear_scores_player_rows(
    storage: StorageBackend,
    scores: InferenceRowPersistenceService,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    turns_prefix = f"games/{game_id}/{perspective}/turns"
    for turn_number in _list_int_segments(storage, turns_prefix):
        document_key = scores.host_turn_document_key(game_id, perspective, turn_number)
        row_key = scores.row_store_key(game_id, perspective, turn_number, player_id)
        if dry_run:
            try:
                storage.get(row_key)
            except NotFoundError:
                continue
            result.deleted_player_entries.append(row_key)
            continue
        try:
            storage.get(row_key)
        except NotFoundError:
            continue
        scores.delete_row(game_id, perspective, turn_number, player_id)
        result.deleted_player_entries.append(row_key)
        remaining = _list_segments(storage, f"{document_key}/{_INFERENCE_ROWS_KEY}")
        if not remaining:
            _delete_document(storage, document_key, dry_run=False, result=result)


def _turns_with_analytic(
    storage: StorageBackend,
    *,
    game_id: int,
    perspective: int,
    analytic_id: str,
) -> list[int]:
    turns_prefix = f"games/{game_id}/{perspective}/turns"
    turns: list[int] = []
    for turn_number in _list_int_segments(storage, turns_prefix):
        analytics_prefix = f"{turns_prefix}/{turn_number}/analytics"
        if analytic_id in _list_segments(storage, analytics_prefix):
            turns.append(turn_number)
    return turns


def _clear_fleet_player_ledgers(
    storage: StorageBackend,
    fleet: FleetSnapshotPersistenceService,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    for turn_number in _turns_with_analytic(
        storage,
        game_id=game_id,
        perspective=perspective,
        analytic_id=FLEET_ANALYTIC_ID,
    ):
        document_key = fleet.document_key(game_id, perspective, turn_number)
        entry_key = f"{document_key}/ledgers/{player_id}"
        if fleet.get_ledger(game_id, perspective, turn_number, player_id) is None:
            continue
        if dry_run:
            result.deleted_player_entries.append(entry_key)
            continue
        fleet.delete_ledger(game_id, perspective, turn_number, player_id)
        result.deleted_player_entries.append(entry_key)


def _clear_perspective_analytics(
    storage: StorageBackend,
    *,
    game_id: int,
    perspective: int,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    prefix = f"games/{game_id}/{perspective}/analytics"
    for analytic_id in sorted(_list_segments(storage, prefix)):
        _delete_document(
            storage,
            f"{prefix}/{analytic_id}",
            dry_run=dry_run,
            result=result,
        )


def _clear_hull_catalog_masks(
    storage: StorageBackend,
    *,
    game_id: int,
    player_id: int | None,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    scores_document = f"games/{game_id}/analytics/{SCORES_ANALYTIC_ID}"
    masks_prefix = f"{scores_document}/{_HULL_MASKS_KEY}"
    if player_id is not None:
        _delete_player_entry(
            storage,
            f"{masks_prefix}/{player_id}",
            dry_run=dry_run,
            result=result,
        )
        return
    player_keys = _list_int_segments(storage, masks_prefix)
    if not player_keys:
        _delete_document(
            storage,
            scores_document,
            dry_run=dry_run,
            result=result,
        )
        return
    for mask_player_id in player_keys:
        _delete_player_entry(
            storage,
            f"{masks_prefix}/{mask_player_id}",
            dry_run=dry_run,
            result=result,
        )
    if dry_run:
        return
    if not _list_segments(storage, masks_prefix):
        _delete_document(storage, scores_document, dry_run=False, result=result)


def _clear_game_global_non_player_analytics(
    storage: StorageBackend,
    *,
    game_id: int,
    dry_run: bool,
    result: ClearAnalyticPersistenceResult,
) -> None:
    prefix = f"games/{game_id}/analytics"
    for analytic_id in sorted(_list_segments(storage, prefix)):
        if analytic_id == SCORES_ANALYTIC_ID:
            # Hull masks are handled separately as player-keyed entries.
            continue
        _delete_document(
            storage,
            f"{prefix}/{analytic_id}",
            dry_run=dry_run,
            result=result,
        )


def clear_analytic_persistence(
    storage: StorageBackend,
    *,
    game_id: int,
    perspective: int | None,
    player_id: int | None,
    dry_run: bool = False,
) -> ClearAnalyticPersistenceResult:
    """Clear analytic persistence matching ``perspective`` / ``player_id`` selectors.

    ``None`` means wildcard (all) for that axis.

    * Turn-scoped and perspective-scoped documents are filtered by ``perspective``.
    * Per-player fleet ledgers, scores inference rows, and hull catalog masks are
      filtered by ``player_id``. When ``player_id`` is wildcard, whole turn/perspective
      analytic documents are removed for matching perspectives.
    * Game-global non-player analytic documents are cleared only when both selectors
      are wildcards.
    """
    result = ClearAnalyticPersistenceResult()
    fleet = FleetSnapshotPersistenceService(storage)
    scores = InferenceRowPersistenceService(storage)
    perspectives = _resolve_perspectives(storage, game_id, perspective)

    for perspective_id in perspectives:
        if player_id is None:
            _clear_turn_analytics_for_all_players(
                storage,
                game_id=game_id,
                perspective=perspective_id,
                dry_run=dry_run,
                result=result,
            )
            _clear_perspective_analytics(
                storage,
                game_id=game_id,
                perspective=perspective_id,
                dry_run=dry_run,
                result=result,
            )
            continue
        _clear_fleet_player_ledgers(
            storage,
            fleet,
            game_id=game_id,
            perspective=perspective_id,
            player_id=player_id,
            dry_run=dry_run,
            result=result,
        )
        _clear_scores_player_rows(
            storage,
            scores,
            game_id=game_id,
            perspective=perspective_id,
            player_id=player_id,
            dry_run=dry_run,
            result=result,
        )

    _clear_hull_catalog_masks(
        storage,
        game_id=game_id,
        player_id=player_id,
        dry_run=dry_run,
        result=result,
    )

    if perspective is None and player_id is None:
        _clear_game_global_non_player_analytics(
            storage,
            game_id=game_id,
            dry_run=dry_run,
            result=result,
        )

    return result


def _default_storage_root() -> Path:
    return Path(".data")


@app.command()
def main(
    game_id: int = typer.Option(..., "--game-id", help="Game id whose analytic state to clear."),
    perspective: str = typer.Option(
        ...,
        "--perspective",
        help="Perspective slot to clear, or '*' for all perspectives.",
    ),
    player: str = typer.Option(
        ...,
        "--player",
        help="Player id to clear, or '*' for all players.",
    ),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root (default: ./.data).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report matching persistence without deleting.",
    ),
) -> None:
    try:
        perspective_selector = parse_selector(perspective, label="perspective")
        player_selector = parse_selector(player, label="player")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if not storage_root.is_dir():
        typer.echo(f"storage root not found: {storage_root}", err=True)
        raise typer.Exit(code=2)

    game_prefix = storage_root / "games" / str(game_id)
    if not game_prefix.is_dir():
        typer.echo(f"game storage not found: {game_prefix}", err=True)
        raise typer.Exit(code=2)

    storage = FileStorageBackend(storage_root.resolve())
    result = clear_analytic_persistence(
        storage,
        game_id=game_id,
        perspective=perspective_selector,
        player_id=player_selector,
        dry_run=dry_run,
    )

    action = "Would clear" if dry_run else "Cleared"
    typer.echo(
        f"{action} {result.total} analytic persistence item(s) "
        f"for game {game_id} "
        f"(perspective={perspective}, player={player})"
    )
    for key in result.deleted_documents:
        typer.echo(f"  document {key}")
    for key in result.deleted_player_entries:
        typer.echo(f"  entry {key}")
    if result.total == 0:
        typer.echo("  (nothing matched)")


if __name__ == "__main__":
    app()
