"""Shared constants for the fleet turn analytic."""

ANALYTIC_ID = "fleet"

FLEET_LEDGERS_KEY = "ledgers"

# Perspective-scoped breakpoint segment for one player's fleet evidence mark.
FLEET_EVIDENCE_MARK_SEGMENT = "fleet-evidence"

# Persisted fleet turn snapshot materialization semantics. Bump conservatively when
# materialization output would change for the same stored RST + scores inputs
# (chain/gap-fill rules, inferred acquisition ingest, observation-inference merge,
# fleet count collapse / merged disposition, exact-set pin retirement).
# Missing or stale versions on read are deleted and re-materialized on next access.
FLEET_MATERIALIZATION_VERSION = 10
