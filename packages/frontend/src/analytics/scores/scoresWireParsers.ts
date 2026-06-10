import type { ScoresInferenceSolution } from '../../api/bff'
import { readMilitaryScoreArithmetic } from './inferenceConstraints'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function readSolutionShipBuild(
  entry: unknown
): NonNullable<ScoresInferenceSolution['shipBuilds']>[number] | null {
  if (!isRecord(entry)) {
    return null
  }
  if (
    typeof entry.comboId !== 'string' ||
    typeof entry.label !== 'string' ||
    typeof entry.count !== 'number'
  ) {
    return null
  }
  return {
    comboId: entry.comboId,
    label: entry.label,
    count: entry.count,
    ...(typeof entry.hullId === 'number' ? { hullId: entry.hullId } : {}),
    ...(typeof entry.engineId === 'number' ? { engineId: entry.engineId } : {}),
    ...(typeof entry.beamId === 'number' ? { beamId: entry.beamId } : {}),
    ...(typeof entry.torpId === 'number' ? { torpId: entry.torpId } : {}),
    ...(typeof entry.beamCount === 'number' ? { beamCount: entry.beamCount } : {}),
    ...(typeof entry.launcherCount === 'number'
      ? { launcherCount: entry.launcherCount }
      : {}),
  }
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
  const shipBuildsRaw = entry.shipBuilds
  const shipBuilds: NonNullable<ScoresInferenceSolution['shipBuilds']> = []
  if (Array.isArray(shipBuildsRaw)) {
    for (const shipBuild of shipBuildsRaw) {
      const parsed = readSolutionShipBuild(shipBuild)
      if (parsed != null) {
        shipBuilds.push(parsed)
      }
    }
  }
  const arithmetic = readMilitaryScoreArithmetic(entry.militaryScoreArithmetic)
  return {
    objectiveValue: entry.objectiveValue,
    actions,
    ...(shipBuilds.length > 0 ? { shipBuilds } : {}),
    ...(arithmetic != null ? { militaryScoreArithmetic: arithmetic } : {}),
  }
}
