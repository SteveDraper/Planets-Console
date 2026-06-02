import type { components } from './schema'

export type LoadAllProgressUpdate = components['schemas']['LoadAllProgressUpdate']
export type LoadAllTurnsResponse = components['schemas']['LoadAllTurnsResponse']

export type LoadAllStreamProgressEvent = LoadAllProgressUpdate & { type: 'progress' }
export type LoadAllStreamCompleteEvent = {
  type: 'complete'
  result: LoadAllTurnsResponse
}
export type LoadAllStreamErrorEvent = { type: 'error'; detail: string }

export type LoadAllStreamEvent =
  | LoadAllStreamProgressEvent
  | LoadAllStreamCompleteEvent
  | LoadAllStreamErrorEvent

const LOAD_ALL_PHASES = ['download', 'import', 'final_turn'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isLoadAllPhase(value: unknown): value is LoadAllProgressUpdate['phase'] {
  return typeof value === 'string' && (LOAD_ALL_PHASES as readonly string[]).includes(value)
}

function parseLoadAllProgressUpdate(value: Record<string, unknown>): LoadAllProgressUpdate | null {
  if (
    !isLoadAllPhase(value.phase) ||
    !isNonNegativeInteger(value.perspective) ||
    !isNonNegativeInteger(value.perspective_total) ||
    !isNonNegativeInteger(value.turn) ||
    !isNonNegativeInteger(value.turn_total) ||
    typeof value.message !== 'string'
  ) {
    return null
  }
  return {
    phase: value.phase,
    perspective: value.perspective,
    perspective_total: value.perspective_total,
    turn: value.turn,
    turn_total: value.turn_total,
    message: value.message,
  }
}

function parseLoadAllTurnsResponse(value: unknown): LoadAllTurnsResponse | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    !Number.isInteger(value.game_id) ||
    typeof value.is_game_finished !== 'boolean' ||
    !Number.isInteger(value.turns_written) ||
    !Number.isInteger(value.turns_skipped) ||
    !Array.isArray(value.perspectives_touched) ||
    !value.perspectives_touched.every((item) => Number.isInteger(item))
  ) {
    return null
  }
  if (
    value.final_turn_load_failures !== undefined &&
    (!Array.isArray(value.final_turn_load_failures) ||
      !value.final_turn_load_failures.every((item) => Number.isInteger(item)))
  ) {
    return null
  }
  return value as LoadAllTurnsResponse
}

/** Parse one NDJSON line from the load-all stream into a typed event, or null when empty. */
export function parseLoadAllStreamEvent(line: string): LoadAllStreamEvent | null {
  const trimmed = line.trim()
  if (!trimmed) {
    return null
  }

  const parsed: unknown = JSON.parse(trimmed)
  if (!isRecord(parsed) || typeof parsed.type !== 'string') {
    return null
  }

  if (parsed.type === 'progress') {
    const progress = parseLoadAllProgressUpdate(parsed)
    return progress ? { type: 'progress', ...progress } : null
  }

  if (parsed.type === 'complete') {
    const result = parseLoadAllTurnsResponse(parsed.result)
    return result ? { type: 'complete', result } : null
  }

  if (parsed.type === 'error' && typeof parsed.detail === 'string') {
    return { type: 'error', detail: parsed.detail }
  }

  return null
}
