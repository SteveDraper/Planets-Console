import type { MilitaryScoreLineItem } from './inferenceConstraints'

/** Player-facing row order within a solution action table. */
export function solutionLineItemDisplayRank(actionId: string): number {
  if (actionId.startsWith('combo_')) {
    return 0
  }
  if (actionId === 'starbase_defense_posts_added_total') {
    return 1
  }
  if (actionId === 'planet_defense_posts_added_total') {
    return 2
  }
  if (actionId.includes('fighter') || actionId.startsWith('fighters_')) {
    return 3
  }
  if (actionId.startsWith('ship_torps_loaded_')) {
    return 4
  }
  return 5
}

export function sortSolutionLineItemsForDisplay(
  lineItems: MilitaryScoreLineItem[]
): MilitaryScoreLineItem[] {
  return [...lineItems]
    .map((line, index) => ({ line, index }))
    .sort((left, right) => {
      const rankDiff =
        solutionLineItemDisplayRank(left.line.actionId) -
        solutionLineItemDisplayRank(right.line.actionId)
      return rankDiff !== 0 ? rankDiff : left.index - right.index
    })
    .map(({ line }) => line)
}
