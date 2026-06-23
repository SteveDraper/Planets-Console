"""Core Fleet turn analytic (registration shell)."""

from api.analytics.catalog import catalog_entry
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.fleet.compute import ANALYTIC_ID, compute_fleet, get_fleet
from api.analytics.registration import TurnAnalyticRegistration

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_fleet,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

__all__ = [
    "ANALYTIC_ID",
    "REGISTRATION",
    "compute_fleet",
    "get_fleet",
]
