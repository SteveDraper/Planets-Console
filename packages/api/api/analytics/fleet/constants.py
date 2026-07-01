"""Shared constants for the fleet turn analytic."""

ANALYTIC_ID = "fleet"

FLEET_LEDGERS_KEY = "ledgers"

# Bounded retries when gap-fill is aborted by concurrent fleet snapshot invalidation.
GAP_FILL_MAX_RETRIES = 10

# Max seconds a waiter blocks on an in-flight coordinated gap-fill before surfacing error.
GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC = 300

# Persisted fleet turn snapshot materialization semantics. Bump conservatively when
# materialization output would change for the same stored RST + scores inputs
# (chain/gap-fill rules, inferred acquisition ingest, observation-inference merge).
# Missing or stale versions on read are deleted and re-materialized on next access.
FLEET_MATERIALIZATION_VERSION = 5
