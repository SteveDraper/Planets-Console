"""Homeworld locator turn analytic registration."""

from api.analytics.catalog import catalog_entry
from api.analytics.homeworld_locator.compute import compute_homeworld_locator
from api.analytics.homeworld_locator.compute_orchestration import (
    HOMEWORLD_BASELINE_STEP,
    HOMEWORLD_COMPUTE_PROFILE,
    HOMEWORLD_PERSISTENCE_POLICY,
    HOMEWORLD_REFINE_STEP,
    HOMEWORLD_SCOPE_KEY_SPEC,
    build_homeworld_baseline_job_wire,
    build_homeworld_refine_job_wire,
    run_homeworld_baseline,
    run_homeworld_refine,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.registration import TurnAnalyticRegistration


def _load_homeworld_export_catalog():
    from api.analytics.homeworld_locator.exports import EXPORT_CATALOG

    return EXPORT_CATALOG


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_homeworld_locator,
    export_catalog_loader=_load_homeworld_export_catalog,
    scope_key_spec=HOMEWORLD_SCOPE_KEY_SPEC,
    compute_profile=HOMEWORLD_COMPUTE_PROFILE,
    persistence_policy=HOMEWORLD_PERSISTENCE_POLICY,
    build_step_job_wires=(
        (HOMEWORLD_BASELINE_STEP, build_homeworld_baseline_job_wire),
        (HOMEWORLD_REFINE_STEP, build_homeworld_refine_job_wire),
    ),
    run_steps=(
        (HOMEWORLD_BASELINE_STEP, run_homeworld_baseline),
        (HOMEWORLD_REFINE_STEP, run_homeworld_refine),
    ),
)
