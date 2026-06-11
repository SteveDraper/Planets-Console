"""Fixed-asset scope for the scores turn analytic."""

from api.analytics.fixed_asset_analytic import FixedAssetAnalytic

ANALYTIC_ID = "scores"


class Scores(FixedAssetAnalytic):
    """Scores turn analytic (scoreboard table and military build inference)."""

    ANALYTIC_ID = ANALYTIC_ID
