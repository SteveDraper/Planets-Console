"""Empty export catalog for the connections analytic."""

from api.analytics.exports.empty import empty_export_catalog_for

ANALYTIC_ID = "connections"
EXPORT_CATALOG = empty_export_catalog_for(ANALYTIC_ID)
