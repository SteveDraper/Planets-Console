"""Homeworld locator analytic identity."""

ANALYTIC_ID = "homeworld-locator"

ATTRIBUTION_INFERRED = "inferred"
ATTRIBUTION_USER_ASSERTED = "user_asserted"

# Bump when layout-prior cost, caps, stand-in policy, or tie-break changes.
# Promote/cull input changes invalidate via persisted promotionThreshold +
# inputFingerprint on layoutPriorSelection -- do not rely on this alone for those.
LAYOUT_PRIOR_ALGORITHM_VERSION = 2
