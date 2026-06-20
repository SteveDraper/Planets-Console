"""Empty export catalog for analytics with no queryable exports yet."""

from api.analytics.exports.catalog import AnalyticExportCatalog


def empty_export_catalog_for(analytic_id: str) -> AnalyticExportCatalog:
    """Return a catalog placeholder for one production analytic id."""
    return AnalyticExportCatalog(analytic_id=analytic_id, is_empty=True)
