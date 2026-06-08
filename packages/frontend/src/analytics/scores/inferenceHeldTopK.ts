import type { ScoresInferenceSolution } from '../../api/bff'
import { HELD_INFERENCE_TOP_K } from '../../api/bff'

export function inferenceSolutionSignature(solution: ScoresInferenceSolution): string {
  const parts: string[] = []
  for (const action of solution.actions) {
    parts.push(`a:${action.actionId}:${action.count}`)
  }
  for (const build of solution.shipBuilds ?? []) {
    parts.push(`c:${build.comboId}:${build.count}`)
  }
  return parts.sort().join('|')
}

export function admitInferenceSolution(
  held: ScoresInferenceSolution[],
  incoming: ScoresInferenceSolution,
  maxHeld: number = HELD_INFERENCE_TOP_K
): ScoresInferenceSolution[] {
  const incomingSignature = inferenceSolutionSignature(incoming)
  if (held.some((row) => inferenceSolutionSignature(row) === incomingSignature)) {
    return held
  }
  if (held.length < maxHeld) {
    return [...held, incoming].sort((left, right) => right.objectiveValue - left.objectiveValue)
  }
  const worstIndex = held.reduce(
    (currentWorst, row, index, rows) =>
      row.objectiveValue < rows[currentWorst].objectiveValue ? index : currentWorst,
    0
  )
  const worst = held[worstIndex]
  if (incoming.objectiveValue <= worst.objectiveValue) {
    return held
  }
  const next = [...held]
  next[worstIndex] = incoming
  return next.sort((left, right) => right.objectiveValue - left.objectiveValue)
}
