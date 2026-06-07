import type { ScoresInferenceSolution } from '../../api/bff'
import { readMilitaryScoreArithmetic } from './inferenceConstraints'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

export type AcceleratedInferenceSegment = {
  segmentId: string
  hostTurn: number
  status: string
  solutionCount: number
  militaryDelta2x: number
  warshipDelta: number
  freighterDelta: number
  solutions: ScoresInferenceSolution[]
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

function readInferenceSolution(entry: unknown): ScoresInferenceSolution | null {
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

export function readAcceleratedInferenceSegments(
  diagnostics: Record<string, unknown>
): AcceleratedInferenceSegment[] | null {
  const raw = diagnostics.accelerated_segments ?? diagnostics.acceleratedSegments
  if (!Array.isArray(raw) || raw.length === 0) {
    return null
  }

  const segments: AcceleratedInferenceSegment[] = []
  for (const entry of raw) {
    if (!isRecord(entry)) {
      continue
    }
    const segmentId =
      typeof entry.segmentId === 'string'
        ? entry.segmentId
        : typeof entry.segment_id === 'string'
          ? entry.segment_id
          : null
    const hostTurn =
      typeof entry.hostTurn === 'number'
        ? entry.hostTurn
        : typeof entry.host_turn === 'number'
          ? entry.host_turn
          : null
    if (segmentId == null || hostTurn == null) {
      continue
    }
    const solutionsRaw = entry.solutions
    const solutions: ScoresInferenceSolution[] = []
    if (Array.isArray(solutionsRaw)) {
      for (const solution of solutionsRaw) {
        const parsed = readInferenceSolution(solution)
        if (parsed != null) {
          solutions.push(parsed)
        }
      }
    }
    segments.push({
      segmentId,
      hostTurn,
      status: typeof entry.status === 'string' ? entry.status : 'unknown',
      solutionCount:
        typeof entry.solutionCount === 'number'
          ? entry.solutionCount
          : typeof entry.solution_count === 'number'
            ? entry.solution_count
            : solutions.length,
      militaryDelta2x:
        typeof entry.militaryDelta2x === 'number'
          ? entry.militaryDelta2x
          : typeof entry.military_delta_2x === 'number'
            ? entry.military_delta_2x
            : 0,
      warshipDelta:
        typeof entry.warshipDelta === 'number'
          ? entry.warshipDelta
          : typeof entry.warship_delta === 'number'
            ? entry.warship_delta
            : 0,
      freighterDelta:
        typeof entry.freighterDelta === 'number'
          ? entry.freighterDelta
          : typeof entry.freighter_delta === 'number'
            ? entry.freighter_delta
            : 0,
      solutions,
    })
  }

  if (segments.length === 0) {
    return null
  }
  return [...segments].sort((left, right) => left.hostTurn - right.hostTurn)
}

export function acceleratedSegmentTitle(
  segment: AcceleratedInferenceSegment,
  scoreboardTurn: number | undefined
): string {
  if (segment.segmentId === 'accel_window') {
    return `Host turn ${segment.hostTurn} (accelerated window)`
  }
  if (segment.segmentId === 'reported_host_turn' && scoreboardTurn != null) {
    return `Host turn ${segment.hostTurn} (on scoreboard row turn ${scoreboardTurn})`
  }
  return `Host turn ${segment.hostTurn}`
}
