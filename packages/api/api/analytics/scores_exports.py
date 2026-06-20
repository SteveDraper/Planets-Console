"""Empty export catalog for the scores analytic."""

from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.scores_assets import ANALYTIC_ID

EXPORT_CATALOG = empty_export_catalog_for(ANALYTIC_ID)
