/**
 * Helpers for manager-owned async hover samples (cartography).
 */

import type { MapHoverContribution, MapHoverSyncBlock } from './mapHoverContributionTypes'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'

export type PendingAsyncHover = {
  contribution: MapHoverContribution
  requestKey: string
  contributor: MapInteractionContributor
}

export function findPendingAsyncHover(
  contributions: readonly MapHoverContribution[],
  contributors: readonly MapInteractionContributor[]
): PendingAsyncHover | null {
  for (const contribution of contributions) {
    for (const block of contribution.blocks) {
      if (block.type !== 'async' || block.status !== 'pending') continue
      const contributor = findFetchContributor(contribution, contributors)
      if (contributor?.fetch == null) continue
      return { contribution, requestKey: block.requestKey, contributor }
    }
  }
  return null
}

function findFetchContributor(
  contribution: MapHoverContribution,
  contributors: readonly MapInteractionContributor[]
): MapInteractionContributor | undefined {
  const exact = contributors.find((c) => c.id === contribution.id)
  if (exact?.fetch != null) return exact
  const prefix = contributors.find(
    (c) => contribution.id === c.id || contribution.id.startsWith(`${c.id}:`)
  )
  if (prefix?.fetch != null) return prefix
  return contributors.find((c) => c.role === contribution.role && c.fetch != null)
}

/** Replace a pending async contribution with ready sync blocks, or drop if empty. */
export function applyReadyAsyncBlocks(
  contributions: readonly MapHoverContribution[],
  requestKey: string,
  blocks: readonly MapHoverSyncBlock[]
): MapHoverContribution[] {
  const out: MapHoverContribution[] = []
  for (const contribution of contributions) {
    const pending = contribution.blocks.find(
      (b) => b.type === 'async' && b.status === 'pending' && b.requestKey === requestKey
    )
    if (pending == null) {
      out.push(contribution)
      continue
    }
    if (blocks.length === 0) continue
    out.push({ ...contribution, blocks })
  }
  return out
}

/** Drop contributions that still have unresolved async pending blocks. */
export function omitPendingAsyncContributions(
  contributions: readonly MapHoverContribution[]
): MapHoverContribution[] {
  return contributions.filter(
    (c) =>
      !c.blocks.some((b) => b.type === 'async' && b.status === 'pending')
  )
}
