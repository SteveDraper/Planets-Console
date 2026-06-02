import type { components } from './schema'

export type LoadAllProgressUpdate = components['schemas']['LoadAllProgressUpdate']
export type LoadAllTurnsResponse = components['schemas']['LoadAllTurnsResponse']

export type LoadAllStreamProgressEvent = LoadAllProgressUpdate & { type: 'progress' }
export type LoadAllStreamCompleteEvent = {
  type: 'complete'
  result: LoadAllTurnsResponse
}
export type LoadAllStreamErrorEvent = components['schemas']['LoadAllStreamErrorEvent']

export type LoadAllStreamEvent =
  | LoadAllStreamProgressEvent
  | LoadAllStreamCompleteEvent
  | LoadAllStreamErrorEvent

const LOAD_ALL_PHASES = new Set<LoadAllProgressUpdate['phase']>([
  'download',
  'import',
  'final_turn',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseNonNegativeInt(value: unknown, fieldName: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new Error(
      `Load-all stream progress event field ${fieldName} must be a non-negative integer.`
    )
  }
  return value
}

function parseIntArray(value: unknown, fieldName: string): number[] {
  if (!Array.isArray(value)) {
    throw new Error(
      `Load-all stream complete event field ${fieldName} must be an array of integers.`
    )
  }
  const items: number[] = []
  for (const entry of value) {
    if (typeof entry !== 'number' || !Number.isInteger(entry)) {
      throw new Error(
        `Load-all stream complete event field ${fieldName} must be an array of integers.`
      )
    }
    items.push(entry)
  }
  return items
}

function parseLoadAllProgressFields(parsed: Record<string, unknown>): LoadAllProgressUpdate {
  const phase = parsed.phase
  if (typeof phase !== 'string' || !LOAD_ALL_PHASES.has(phase as LoadAllProgressUpdate['phase'])) {
    throw new Error('Load-all stream progress event has an invalid shape.')
  }
  const message = parsed.message
  if (typeof message !== 'string') {
    throw new Error('Load-all stream progress event has an invalid shape.')
  }
  return {
    phase: phase as LoadAllProgressUpdate['phase'],
    perspective: parseNonNegativeInt(parsed.perspective, 'perspective'),
    perspective_total: parseNonNegativeInt(parsed.perspective_total, 'perspective_total'),
    turn: parseNonNegativeInt(parsed.turn, 'turn'),
    turn_total: parseNonNegativeInt(parsed.turn_total, 'turn_total'),
    message,
  }
}

function parseLoadAllTurnsResult(parsed: Record<string, unknown>): LoadAllTurnsResponse {
  if (typeof parsed.game_id !== 'number' || !Number.isInteger(parsed.game_id)) {
    throw new Error('Load-all stream complete event result.game_id must be an integer.')
  }
  if (typeof parsed.is_game_finished !== 'boolean') {
    throw new Error(
      'Load-all stream complete event result.is_game_finished must be a boolean.'
    )
  }
  if (
    typeof parsed.turns_written !== 'number' ||
    !Number.isInteger(parsed.turns_written) ||
    parsed.turns_written < 0
  ) {
    throw new Error(
      'Load-all stream complete event result.turns_written must be a non-negative integer.'
    )
  }
  if (
    typeof parsed.turns_skipped !== 'number' ||
    !Number.isInteger(parsed.turns_skipped) ||
    parsed.turns_skipped < 0
  ) {
    throw new Error(
      'Load-all stream complete event result.turns_skipped must be a non-negative integer.'
    )
  }

  const result: LoadAllTurnsResponse = {
    game_id: parsed.game_id,
    is_game_finished: parsed.is_game_finished,
    turns_written: parsed.turns_written,
    turns_skipped: parsed.turns_skipped,
  }

  if (parsed.perspectives_touched !== undefined) {
    result.perspectives_touched = parseIntArray(
      parsed.perspectives_touched,
      'perspectives_touched'
    )
  }
  if (parsed.final_turn_load_failures !== undefined) {
    result.final_turn_load_failures = parseIntArray(
      parsed.final_turn_load_failures,
      'final_turn_load_failures'
    )
  }

  return result
}

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

  if (!isRecord(parsed) || typeof parsed.type !== 'string') {
    throw new Error('Load-all stream event is missing a type field.')
  }

  switch (parsed.type) {
    case 'progress': {
      const progress = parseLoadAllProgressFields(parsed)
      return { type: 'progress', ...progress }
    }
    case 'complete': {
      if (!isRecord(parsed.result)) {
        throw new Error('Load-all stream complete event has an invalid result shape.')
      }
      return { type: 'complete', result: parseLoadAllTurnsResult(parsed.result) }
    }
    case 'error': {
      if (typeof parsed.detail !== 'string') {
        throw new Error('Load-all stream error event has an invalid shape.')
      }
      return { type: 'error', detail: parsed.detail }
    }
    default:
      throw new Error(`Load-all stream returned unknown event type: ${parsed.type}`)
  }
}
