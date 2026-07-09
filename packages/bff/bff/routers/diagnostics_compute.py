"""Compute orchestrator diagnostics BFF routes."""

from __future__ import annotations

from api.compute.diagnostics import (
    ShellContextKey,
    compute_diagnostics_enabled,
    get_compute_diagnostics_controller,
    snapshot_to_wire,
)
from fastapi import APIRouter, Body, Query

from bff.errors import BFFNotFoundError
from bff.transport.compute_diagnostics_responses import (
    ComputeDiagnosticsAllowlistRequest,
    ComputeDiagnosticsClientStreamReport,
    ComputeDiagnosticsFreezeRequest,
    ComputeDiagnosticsSingleStepRequest,
    ComputeDiagnosticsSnapshotResponse,
)

router = APIRouter()

_client_stream_reports: dict[str, list[dict]] = {}


def _require_compute_diagnostics_enabled() -> None:
    if not compute_diagnostics_enabled():
        raise BFFNotFoundError("Compute diagnostics are disabled on this server")


def _shell_key(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> ShellContextKey:
    return ShellContextKey(game_id=game_id, perspective=perspective, turn=turn)


def _client_streams_for_shell(shell: ShellContextKey) -> list[dict]:
    key = f"{shell.game_id}:{shell.perspective}:{shell.turn}"
    return list(_client_stream_reports.get(key, []))


@router.get("/compute/enabled")
def get_compute_diagnostics_enabled() -> dict[str, bool]:
    """Return whether compute diagnostics are enabled on this server."""
    return {"enabled": compute_diagnostics_enabled()}


@router.get("/compute/snapshot", response_model=ComputeDiagnosticsSnapshotResponse)
def get_compute_diagnostics_snapshot(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
    client_streams: str | None = Query(default=None, alias="clientStreams"),
) -> ComputeDiagnosticsSnapshotResponse:
    """Return a read-only compute diagnostics snapshot for one shell context."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=game_id, perspective=perspective, turn=turn)
    controller = get_compute_diagnostics_controller()
    wire = snapshot_to_wire(controller.snapshot(shell))
    if client_streams:
        import json

        try:
            parsed = json.loads(client_streams)
        except json.JSONDecodeError as exc:
            raise BFFNotFoundError("clientStreams must be valid JSON") from exc
        if isinstance(parsed, list):
            wire["clientStreams"] = parsed
    if "clientStreams" not in wire:
        wire["clientStreams"] = _client_streams_for_shell(shell)
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.put("/compute/freeze", response_model=ComputeDiagnosticsSnapshotResponse)
def put_compute_diagnostics_freeze(
    body: ComputeDiagnosticsFreezeRequest = Body(...),
) -> ComputeDiagnosticsSnapshotResponse:
    """Arm or disarm compute freeze mode for one game."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=body.game_id, perspective=body.perspective, turn=body.turn)
    controller = get_compute_diagnostics_controller()
    controller.set_freeze_armed(shell, freeze_armed=body.freeze_armed)
    wire = snapshot_to_wire(controller.snapshot(shell))
    wire["clientStreams"] = _client_streams_for_shell(shell)
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.put("/compute/allowlist", response_model=ComputeDiagnosticsSnapshotResponse)
def put_compute_diagnostics_allowlist(
    body: ComputeDiagnosticsAllowlistRequest = Body(...),
) -> ComputeDiagnosticsSnapshotResponse:
    """Set the per-shell player allowlist while freeze mode is armed."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=body.game_id, perspective=body.perspective, turn=body.turn)
    controller = get_compute_diagnostics_controller()
    controller.set_allowlist(shell, frozenset(body.player_ids))
    wire = snapshot_to_wire(controller.snapshot(shell))
    wire["clientStreams"] = _client_streams_for_shell(shell)
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.post("/compute/single-step", response_model=ComputeDiagnosticsSnapshotResponse)
def post_compute_diagnostics_single_step(
    body: ComputeDiagnosticsSingleStepRequest = Body(...),
) -> ComputeDiagnosticsSnapshotResponse:
    """Release exactly one pool work item, then re-freeze unless allowlisted."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=body.game_id, perspective=body.perspective, turn=body.turn)
    controller = get_compute_diagnostics_controller()
    controller.single_step(shell)
    wire = snapshot_to_wire(controller.snapshot(shell))
    wire["clientStreams"] = _client_streams_for_shell(shell)
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.put("/compute/client-streams")
def put_compute_diagnostics_client_streams(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
    reports: list[ComputeDiagnosticsClientStreamReport] = Body(...),
) -> dict[str, str]:
    """Accept client stream lifecycle telemetry for one shell context."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=game_id, perspective=perspective, turn=turn)
    key = f"{shell.game_id}:{shell.perspective}:{shell.turn}"
    _client_stream_reports[key] = [report.model_dump(by_alias=True) for report in reports]
    return {"status": "ok"}


def reset_compute_diagnostics_client_streams_for_tests() -> None:
    _client_stream_reports.clear()
