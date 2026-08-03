"""Homeworld locator analytic identity."""

ANALYTIC_ID = "homeworld-locator"

ATTRIBUTION_INFERRED = "inferred"
# Wire/FE-compat only: derive at emit from ``asserted_cue``. Not durable authority
# (ADR 0010); do not store as parallel to asserted location provenances.
ATTRIBUTION_USER_ASSERTED = "user_asserted"

# Bump when baseline candidacy policy changes (cluster FoW density credit, orphan
# emission gates, etc.). Checked in needs_baseline_recompute so persisted
# game-global candidates recompute after algorithm changes.
HOMEWORLD_BASELINE_ALGORITHM_VERSION = 1

# Bump when turn-scoped evidence refine policy changes (ownership evidence,
# origin-distance / single-SB rules that rewrite aggregates). Checked in
# evidence_refined_through_shell so shell ensure re-runs the chain after deploys.
# 0 on disk = pre-version / legacy aggregates.
HOMEWORLD_EVIDENCE_ALGORITHM_VERSION = 4

# Bump when layout-prior cost, caps, stand-in policy, tie-break, or default
# solver identity changes (e.g. soft evidence family, anneal default). Post-promote/cull
# candidate-set, soft-evidence λ, and OD observation identity invalidate via
# inputFingerprint + evidenceLambda + evidenceFingerprint on layoutPriorSelection;
# evidence refine rewrites clear the selection block (defense in depth).
LAYOUT_PRIOR_ALGORITHM_VERSION = 10
