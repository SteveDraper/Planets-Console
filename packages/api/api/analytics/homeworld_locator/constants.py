"""Homeworld locator analytic identity."""

ANALYTIC_ID = "homeworld-locator"

ATTRIBUTION_INFERRED = "inferred"
ATTRIBUTION_USER_ASSERTED = "user_asserted"

# Bump when layout-prior cost, caps, stand-in policy, tie-break, or default
# solver identity changes (e.g. soft evidence family, anneal default). Post-promote/cull
# candidate-set changes invalidate via inputFingerprint on layoutPriorSelection;
# evidence refine rewrites clear the selection block.
LAYOUT_PRIOR_ALGORITHM_VERSION = 7
