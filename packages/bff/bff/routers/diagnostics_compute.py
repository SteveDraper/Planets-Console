"""Compute orchestrator diagnostics BFF routes."""

from __future__ import annotations

from api.services import compute_diagnostics_service as compute_diagnostics
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
    if not compute_diagnostics.compute_diagnostics_enabled():
        raise BFFNotFoundError("Compute diagnostics are disabled on this server")


@router.get("/compute/enabled")
def get_compute_diagnostics_enabled() -> dict[str, bool]:
    """Return whether compute diagnostics are enabled on this server."""
    return {"enabled": compute_diagnostics.compute_diagnostics_enabled()}


@router.get("/compute/snapshot", response_model=ComputeDiagnosticsSnapshotResponse)
def get_compute_diagnostics_snapshot(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
) -> ComputeDiagnosticsSnapshotResponse:
    """Return a read-only compute diagnostics snapshot for one shell context."""
    _require_compute_diagnostics_enabled()
    wire = compute_diagnostics.get_compute_diagnostics_snapshot_wire(
        game_id=game_id,
        perspective=perspective,
        turn=turn,
    )
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.get("/compute/freeze-status", response_model=ComputeDiagnosticsFreezeStatusResponse)
def get_compute_diagnostics_freeze_status(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
) -> ComputeDiagnosticsFreezeStatusResponse:
    """Return freeze armed state and allowlist for one shell (no heavy snapshot)."""
    _require_compute_diagnostics_enabled()
    freeze_armed, allowlisted = compute_diagnostics.get_compute_diagnostics_freeze_status(
        game_id=game_id,
        perspective=perspective,
        turn=turn,
    )
    return ComputeDiagnosticsFreezeStatusResponse(
        shell=ComputeDiagnosticsShellContext(
            game_id=game_id,
            perspective=perspective,
            turn=turn,
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
    compute_diagnostics.set_compute_diagnostics_freeze_armed(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
        freeze_armed=body.freeze_armed,
    )
    wire = compute_diagnostics.get_compute_diagnostics_snapshot_wire(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
    )
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.put("/compute/allowlist", response_model=ComputeDiagnosticsSnapshotResponse)
def put_compute_diagnostics_allowlist(
    body: ComputeDiagnosticsAllowlistRequest = Body(...),
) -> ComputeDiagnosticsSnapshotResponse:
    """Set the per-shell focus player allowlist while freeze mode is armed."""
    _require_compute_diagnostics_enabled()
    compute_diagnostics.set_compute_diagnostics_allowlist(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
        player_ids=frozenset(body.player_ids),
    )
    wire = compute_diagnostics.get_compute_diagnostics_snapshot_wire(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
    )
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)


@router.post("/compute/single-step", response_model=ComputeDiagnosticsSnapshotResponse)
def post_compute_diagnostics_single_step(
    body: ComputeDiagnosticsSingleStepRequest = Body(...),
) -> ComputeDiagnosticsSnapshotResponse:
    """Release one in-focus compute step, then re-freeze (allowlist is focus, not free-run)."""
    _require_compute_diagnostics_enabled()
    compute_diagnostics.run_compute_diagnostics_single_step(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
    )
    wire = compute_diagnostics.get_compute_diagnostics_snapshot_wire(
        game_id=body.game_id,
        perspective=body.perspective,
        turn=body.turn,
    )
    return ComputeDiagnosticsSnapshotResponse.model_validate(wire)
