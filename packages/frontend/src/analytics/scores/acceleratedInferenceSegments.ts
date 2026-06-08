import type { ScoresInferenceSolution } from '../../api/bff'
import { isRecord, readInferenceSolution } from './scoresWireParsers'

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

export function readAcceleratedInferenceSegments(
  diagnostics: Record<string, unknown>
): AcceleratedInferenceSegment[] | null {
  const raw = diagnostics.accelerated_segments
  if (!Array.isArray(raw) || raw.length === 0) {
    return null
  }

  const segments: AcceleratedInferenceSegment[] = []
  for (const entry of raw) {
    if (!isRecord(entry)) {
      continue
    }
    if (typeof entry.segmentId !== 'string' || typeof entry.hostTurn !== 'number') {
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
      segmentId: entry.segmentId,
      hostTurn: entry.hostTurn,
      status: typeof entry.status === 'string' ? entry.status : 'unknown',
      solutionCount:
        typeof entry.solutionCount === 'number' ? entry.solutionCount : solutions.length,
      militaryDelta2x: typeof entry.militaryDelta2x === 'number' ? entry.militaryDelta2x : 0,
      warshipDelta: typeof entry.warshipDelta === 'number' ? entry.warshipDelta : 0,
      freighterDelta: typeof entry.freighterDelta === 'number' ? entry.freighterDelta : 0,
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
