import type { ScoresInferenceRowDetail } from '../../api/bff'
import { isRecord } from './scoresWireParsers'

export type InferenceRunSummary = {
  statusLabel?: string
  wallTimeSeconds?: number
}

function readFirstString(
  record: Record<string, unknown> | null,
  ...keys: string[]
): string | undefined {
  if (record == null) {
    return undefined
  }
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.length > 0) {
      return value
    }
  }
  return undefined
}

function readFirstNumber(
  record: Record<string, unknown> | null,
  ...keys: string[]
): number | undefined {
  if (record == null) {
    return undefined
  }
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number') {
      return value
    }
  }
  return undefined
}

export function formatInferenceStatusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

export function readInferenceRunSummary(
  detail: ScoresInferenceRowDetail,
  diagnostics: Record<string, unknown>
): InferenceRunSummary {
  const solverRecord = isRecord(diagnostics.solver) ? diagnostics.solver : null

  const overallStatus =
    typeof detail.status === 'string' && detail.status.length > 0
      ? detail.status
      : readFirstString(solverRecord, 'status', 'solver_status', 'solverStatus')

  return {
    statusLabel:
      overallStatus != null ? formatInferenceStatusLabel(overallStatus) : undefined,
    wallTimeSeconds: readFirstNumber(solverRecord, 'wall_time_seconds', 'wallTimeSeconds'),
  }
}
