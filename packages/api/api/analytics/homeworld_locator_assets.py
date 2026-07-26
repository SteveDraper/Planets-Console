"""Fixed-asset scope for the homeworld locator analytic."""

from api.analytics.fixed_asset_analytic import FixedAssetAnalytic
from api.analytics.homeworld_locator.constants import ANALYTIC_ID


class HomeworldLocator(FixedAssetAnalytic):
    """Homeworld locator analytic (layout distribution assets, etc.)."""

    ANALYTIC_ID = ANALYTIC_ID
