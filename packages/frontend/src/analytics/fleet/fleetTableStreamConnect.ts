import type { AnalyticShellScope } from '../../api/bff'
import { fetchFleetTableStream } from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'

export const FLEET_TABLE_STREAM_ALREADY_ACTIVE_DETAIL =
  'A fleet table stream is already active for this scope.'

const STREAM_RETRY_INITIAL_MS = 50
const STREAM_RETRY_MAX_ATTEMPTS = 15
const STREAM_RETRY_MAX_DELAY_MS = 1000

const STREAM_INCOMPLETE_RETRY_INITIAL_MS = 250
const STREAM_INCOMPLETE_RETRY_MAX_ATTEMPTS = 3
const STREAM_INCOMPLETE_RETRY_MAX_DELAY_MS = 2000

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function isScopeLevelStreamConflict(event: FleetTableStreamEvent): boolean {
  return (
    event.type === 'error' &&
    event.playerId == null &&
    event.detail === FLEET_TABLE_STREAM_ALREADY_ACTIVE_DETAIL
  )
}

export type FleetTableStreamConnectResult =
  | 'ok'
  | 'aborted'
  | 'conflict_exhausted'
  | 'incomplete_exhausted'

export async function connectFleetTableStream(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: FleetTableStreamEvent) => void
  }
): Promise<FleetTableStreamConnectResult> {
  for (let attempt = 0; attempt < STREAM_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (handlers.signal.aborted) {
      return 'aborted'
    }

    let scopeConflict = false

    try {
      await fetchFleetTableStream(scope, playerIds, {
        signal: handlers.signal,
        onEvent: (event) => {
          if (isScopeLevelStreamConflict(event)) {
            scopeConflict = true
            return
          }
          handlers.onEvent(event)
        },
      })
    } catch (error) {
      if (handlers.signal.aborted) {
        return 'aborted'
      }
      throw error
    }

    if (handlers.signal.aborted) {
      return 'aborted'
    }
    if (!scopeConflict) {
      return 'ok'
    }

    const delayMs = Math.min(STREAM_RETRY_INITIAL_MS * 2 ** attempt, STREAM_RETRY_MAX_DELAY_MS)
    await sleep(delayMs)
  }

  return 'conflict_exhausted'
}

export async function connectFleetTableStreamUntilComplete(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: FleetTableStreamEvent) => void
    hasPendingPlayers: () => boolean
  }
): Promise<FleetTableStreamConnectResult> {
  for (let attempt = 0; attempt < STREAM_INCOMPLETE_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (handlers.signal.aborted) {
      return 'aborted'
    }

    const result = await connectFleetTableStream(scope, playerIds, {
      signal: handlers.signal,
      onEvent: handlers.onEvent,
    })

    if (handlers.signal.aborted) {
      return 'aborted'
    }
    if (result === 'conflict_exhausted') {
      return result
    }
    if (!handlers.hasPendingPlayers()) {
      return 'ok'
    }

    const delayMs = Math.min(
      STREAM_INCOMPLETE_RETRY_INITIAL_MS * 2 ** attempt,
      STREAM_INCOMPLETE_RETRY_MAX_DELAY_MS
    )
    await sleep(delayMs)
  }

  return 'incomplete_exhausted'
}
