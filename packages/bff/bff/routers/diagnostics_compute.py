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
    ComputeDiagnosticsFreezeRequest,
    ComputeDiagnosticsFreezeStatusResponse,
    ComputeDiagnosticsShellContext,
    ComputeDiagnosticsSingleStepRequest,
    ComputeDiagnosticsSnapshotResponse,
)

router = APIRouter()


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


@router.get("/compute/enabled")
def get_compute_diagnostics_enabled() -> dict[str, bool]:
    """Return whether compute diagnostics are enabled on this server."""
    return {"enabled": compute_diagnostics_enabled()}


@router.get("/compute/snapshot", response_model=ComputeDiagnosticsSnapshotResponse)
def get_compute_diagnostics_snapshot(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
) -> ComputeDiagnosticsSnapshotResponse:
    """Return a read-only compute diagnostics snapshot for one shell context."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=game_id, perspective=perspective, turn=turn)
    controller = get_compute_diagnostics_controller()
    wire = snapshot_to_wire(controller.snapshot(shell))
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.get("/compute/freeze-status", response_model=ComputeDiagnosticsFreezeStatusResponse)
def get_compute_diagnostics_freeze_status(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
) -> ComputeDiagnosticsFreezeStatusResponse:
    """Return freeze armed state and allowlist for one shell (no heavy snapshot)."""
    _require_compute_diagnostics_enabled()
    shell = _shell_key(game_id=game_id, perspective=perspective, turn=turn)
    controller = get_compute_diagnostics_controller()
    freeze_armed, allowlisted = controller.freeze_status(shell)
    return ComputeDiagnosticsFreezeStatusResponse(
        shell=ComputeDiagnosticsShellContext(
            game_id=shell.game_id,
            perspective=shell.perspective,
            turn=shell.turn,
        ),
        freeze_armed=freeze_armed,
        allowlisted_player_ids=sorted(allowlisted),
    )


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
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)
