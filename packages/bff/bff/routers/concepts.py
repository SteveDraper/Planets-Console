"""Global game concept routes (no game or turn scope)."""

from api.transport.concept_black_holes import (
    BlackHoleConceptConstantsResponse as CoreBlackHoleConceptConstantsResponse,
)
from fastapi import APIRouter

from bff.core_client import get_core_client
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)
from bff.transport.concept_responses import BlackHoleConceptConstantsResponse

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get(
    "/stellar-cartography/black-holes",
    response_model=BlackHoleConceptConstantsResponse,
)
def get_black_hole_concept_constants(include: IncludeDiagnostics = False) -> object:
    """Static black-hole geometry constants via ``CoreClient``."""
    core = get_core_client()
    bff_path = "/concepts/stellar-cartography/black-holes"
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        handler="get_black_hole_concept_constants",
    )

    def load_constants() -> BlackHoleConceptConstantsResponse:
        constants: CoreBlackHoleConceptConstantsResponse = core.black_hole_concept_constants()
        return BlackHoleConceptConstantsResponse(
            ergosphereBandCount=constants.ergosphere_band_count,
            haloExtraLy=constants.halo_extra_ly,
        )

    result = with_timed_child(
        root,
        "get_black_hole_concept_constants",
        "total",
        load_constants,
    )
    return finish_response(result, root)
