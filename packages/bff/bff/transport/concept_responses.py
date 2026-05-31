"""BFF response models for global game concept routes."""

from bff.transport.game_responses import OmitNullDiagnosticsBase


class BlackHoleConceptConstantsResponse(OmitNullDiagnosticsBase):
    """Static black-hole geometry from Core (ergosphere bands, cosmetic halo extent)."""

    ergosphereBandCount: int
    haloExtraLy: int
