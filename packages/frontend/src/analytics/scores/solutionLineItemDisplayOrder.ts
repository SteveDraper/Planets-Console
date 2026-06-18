import { inferenceActionDisplayRank, isComboActionId } from './inferenceActionFamily'
import type { MilitaryScoreLineItem } from './inferenceConstraints'

/** Player-facing row order within a solution action table. */
export function solutionLineItemDisplayRank(actionId: string): number {
  return inferenceActionDisplayRank(actionId)
}

/** Player-facing action label; aggregate rows include the built count in brackets. */
export function formatSolutionLineItemLabel(line: MilitaryScoreLineItem): string {
  if (isComboActionId(line.actionId)) {
    return line.label
  }
  return `${line.label} (${line.count})`
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
