"""Shared constants for the compute orchestrator."""

# Default seconds an orchestration-plane ensure waiter blocks before failing.
# Ported from the former fleet gap-fill waiter timeout (#204). Timeout fails the
# waiter only; in-flight DAG work keeps running for attach / retry / streams.
ENSURE_WAIT_TIMEOUT_SEC = 300.0
