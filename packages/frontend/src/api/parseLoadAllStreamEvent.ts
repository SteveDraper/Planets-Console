import type { components } from './schema'
import {
  formatLoadAllStreamValidationError,
  loadAllStreamEventSchema,
  type ParsedLoadAllStreamEvent,
} from './loadAllStreamEventSchema'

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

const LOAD_ALL_EVENT_TYPES = new Set(['progress', 'complete', 'error'])

function assertHasEventType(parsed: unknown): asserts parsed is Record<string, unknown> & {
  type: string
} {
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Load-all stream event is missing a type field.')
  }
  const type = (parsed as Record<string, unknown>).type
  if (typeof type !== 'string') {
    throw new Error('Load-all stream event is missing a type field.')
  }
  if (!LOAD_ALL_EVENT_TYPES.has(type)) {
    throw new Error(`Load-all stream returned unknown event type: ${type}`)
  }
}

function toLoadAllStreamEvent(parsed: ParsedLoadAllStreamEvent): LoadAllStreamEvent {
  return parsed
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

  assertHasEventType(parsed)

  const result = loadAllStreamEventSchema.safeParse(parsed)
  if (!result.success) {
    throw new Error(formatLoadAllStreamValidationError(result.error))
  }

  return toLoadAllStreamEvent(result.data)
}
