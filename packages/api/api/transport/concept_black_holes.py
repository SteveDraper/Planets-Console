"""HTTP contracts for global game concept: black hole constants."""

from pydantic import BaseModel, Field


class BlackHoleConceptConstantsResponse(BaseModel):
    ergosphere_band_count: int = Field(..., ge=1)
    halo_extra_ly: int = Field(..., ge=0)
