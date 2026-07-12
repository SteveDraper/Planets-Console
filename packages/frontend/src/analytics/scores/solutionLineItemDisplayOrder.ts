import { inferenceActionDisplayRank, isComboActionId } from './inferenceActionFamily'
import type { MilitaryScoreLineItem } from './inferenceConstraints'

/** Player-facing row order within a solution action table. */
export function solutionLineItemDisplayRank(actionId: string): number {
  return inferenceActionDisplayRank(actionId)
}

/** Player-facing action label; aggregates use brackets, multi-copy ships use ``Nx``. */
export function formatSolutionLineItemLabel(line: MilitaryScoreLineItem): string {
  if (isComboActionId(line.actionId)) {
    // Match the non-arithmetic fallback and scores summary (e.g. ``2x Freighter``).
    // Count 1 stays bare so warship labels that already embed fit details are unchanged.
    return line.count > 1 ? `${line.count}x ${line.label}` : line.label
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
