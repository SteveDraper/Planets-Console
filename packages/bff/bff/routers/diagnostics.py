"""Read-only access to the most recently captured per-request diagnostic trees."""

from fastapi import APIRouter

from bff.diagnostics_buffer import get_diagnostics_buffer

router = APIRouter()


def recent_diagnostics_response() -> dict:
    """Shared body for ``/diagnostics/recent`` (BFF router and root-server alias)."""
    return {"items": get_diagnostics_buffer().recent()}


@router.get("/recent")
def get_recent_diagnostics():
    """Return entries captured when handlers were invoked with ``includeDiagnostics``."""
    return recent_diagnostics_response()
