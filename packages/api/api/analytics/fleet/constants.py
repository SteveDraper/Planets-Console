"""Shared constants for the fleet turn analytic."""

ANALYTIC_ID = "fleet"

FLEET_LEDGERS_KEY = "ledgers"

# Max seconds a waiter blocks on an in-flight coordinated gap-fill before surfacing error.
GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC = 300

# Quiet period after the last target_turn bump before the leader starts unwind.
# Waiters notify via threading.Condition; this bounds how long the leader waits
# for late joiners that raise target_turn.
GAP_FILL_TARGET_TURN_COLLECT_SEC = 0.05

# Persisted fleet turn snapshot materialization semantics. Bump conservatively when
# materialization output would change for the same stored RST + scores inputs
# (chain/gap-fill rules, inferred acquisition ingest, observation-inference merge).
# Missing or stale versions on read are deleted and re-materialized on next access.
FLEET_MATERIALIZATION_VERSION = 8
