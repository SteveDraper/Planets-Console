import type { ScoresInferenceSolution } from '../../api/bff'
import { readMilitaryScoreArithmetic } from './inferenceConstraints'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function readSolutionAction(entry: unknown): ScoresInferenceSolution['actions'][number] | null {
  if (!isRecord(entry)) {
    return null
  }
  if (
    typeof entry.actionId !== 'string' ||
    typeof entry.label !== 'string' ||
    typeof entry.count !== 'number'
  ) {
    return null
  }
  return {
    actionId: entry.actionId,
    label: entry.label,
    count: entry.count,
  }
}

export function readInferenceSolution(entry: unknown): ScoresInferenceSolution | null {
  if (!isRecord(entry)) {
    return null
  }
  if (typeof entry.objectiveValue !== 'number') {
    return null
  }
  const actionsRaw = entry.actions
  const actions: ScoresInferenceSolution['actions'] = []
  if (Array.isArray(actionsRaw)) {
    for (const action of actionsRaw) {
      const parsed = readSolutionAction(action)
      if (parsed != null) {
        actions.push(parsed)
      }
    }
  }
  const arithmetic = readMilitaryScoreArithmetic(entry.militaryScoreArithmetic)
  return {
    objectiveValue: entry.objectiveValue,
    actions,
    ...(arithmetic != null ? { militaryScoreArithmetic: arithmetic } : {}),
  }
}
