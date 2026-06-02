import {
  formatLoadAllStreamValidationError,
  loadAllStreamEventSchema,
  type LoadAllProgressUpdate,
  type LoadAllStreamEvent,
  type LoadAllTurnsResponse,
} from './loadAllStreamEventSchema'

export type { LoadAllProgressUpdate, LoadAllStreamEvent, LoadAllTurnsResponse }

/** Parse one NDJSON line from the load-all stream into a typed event, or null when empty. */
export function parseLoadAllStreamEvent(line: string): LoadAllStreamEvent | null {
  const trimmed = line.trim()
  if (!trimmed) {
    return null
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error('Load-all stream returned invalid JSON.')
  }

  const result = loadAllStreamEventSchema.safeParse(parsed)
  if (!result.success) {
    throw new Error(formatLoadAllStreamValidationError(result.error))
  }

  return result.data
}
