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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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
      if (typeof parsed.message !== 'string' || typeof parsed.phase !== 'string') {
        throw new Error('Load-all stream progress event has an invalid shape.')
      }
      const { type: _type, ...progress } = parsed
      return { type: 'progress', ...(progress as LoadAllProgressUpdate) }
    }
    case 'complete': {
      if (!isRecord(parsed.result)) {
        throw new Error('Load-all stream complete event has an invalid result shape.')
      }
      return { type: 'complete', result: parsed.result as LoadAllTurnsResponse }
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
