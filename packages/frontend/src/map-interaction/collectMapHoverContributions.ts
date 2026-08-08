/**
 * Collect hover contributions from registered contributors for one surface
 * compose pass: pointer ``hitTest`` results unioned with optional sticky
 * contributions (no pointer / no hit under the cursor).
 */

import type { MapHoverContribution } from './mapHoverContributionTypes'
import type {
  MapHitContext,
  MapInteractionContributor,
} from './mapInteractionContributorTypes'

/**
 * For each contributor: prefer a live ``hitTest`` result; otherwise take
 * ``stickyContribution`` when present. Sticky never duplicates a hitTest
 * result from the same contributor.
 */
export function collectMapHoverContributions(
  contributors: readonly MapInteractionContributor[],
  hit: MapHitContext | null
): MapHoverContribution[] {
  const out: MapHoverContribution[] = []
  for (const contributor of contributors) {
    const fromHit = hit != null ? contributor.hitTest(hit) : null
    if (fromHit != null) {
      out.push(fromHit)
      continue
    }
    const sticky = contributor.stickyContribution?.() ?? null
    if (sticky != null) out.push(sticky)
  }
  return out
}
