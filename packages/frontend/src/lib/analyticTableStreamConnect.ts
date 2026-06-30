import type { AnalyticShellScope } from '../api/bff'

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

type StreamErrorEvent = {
  type: string
  playerId?: number | null
  detail?: string
}

function isScopeLevelStreamConflict<TEvent extends StreamErrorEvent>(
  event: TEvent,
  conflictAlreadyActiveDetail: string
): boolean {
  return (
    event.type === 'error' &&
    event.playerId == null &&
    event.detail === conflictAlreadyActiveDetail
  )
}

export type AnalyticTableStreamConnectResult =
  | 'ok'
  | 'aborted'
  | 'conflict_exhausted'
  | 'incomplete_exhausted'

type FetchAnalyticTableStream<TEvent> = (
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: TEvent) => void
  }
) => Promise<void>

export async function connectAnalyticTableStream<TEvent extends StreamErrorEvent>(
  scope: AnalyticShellScope,
  playerIds: number[],
  options: {
    conflictAlreadyActiveDetail: string
    fetchStream: FetchAnalyticTableStream<TEvent>
    signal: AbortSignal
    onEvent: (event: TEvent) => void
    interceptEvent?: (event: TEvent, scope: AnalyticShellScope) => void
  }
): Promise<AnalyticTableStreamConnectResult> {
  const { conflictAlreadyActiveDetail, fetchStream, signal, onEvent, interceptEvent } = options

  for (let attempt = 0; attempt < STREAM_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (signal.aborted) {
      return 'aborted'
    }

    let scopeConflict = false

    try {
      await fetchStream(scope, playerIds, {
        signal,
        onEvent: (event) => {
          if (isScopeLevelStreamConflict(event, conflictAlreadyActiveDetail)) {
            scopeConflict = true
            return
          }
          interceptEvent?.(event, scope)
          onEvent(event)
        },
      })
    } catch (error) {
      if (signal.aborted) {
        return 'aborted'
      }
      throw error
    }

    if (signal.aborted) {
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

export async function connectAnalyticTableStreamUntilComplete<TEvent extends StreamErrorEvent>(
  scope: AnalyticShellScope,
  playerIds: number[],
  options: {
    conflictAlreadyActiveDetail: string
    fetchStream: FetchAnalyticTableStream<TEvent>
    signal: AbortSignal
    onEvent: (event: TEvent) => void
    hasPending: () => boolean
    interceptEvent?: (event: TEvent, scope: AnalyticShellScope) => void
    onBeforeIncompleteRetries?: (scope: AnalyticShellScope) => void
  }
): Promise<AnalyticTableStreamConnectResult> {
  const {
    conflictAlreadyActiveDetail,
    fetchStream,
    signal,
    onEvent,
    hasPending,
    interceptEvent,
    onBeforeIncompleteRetries,
  } = options

  onBeforeIncompleteRetries?.(scope)

  for (let attempt = 0; attempt < STREAM_INCOMPLETE_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (signal.aborted) {
      return 'aborted'
    }

    const result = await connectAnalyticTableStream(scope, playerIds, {
      conflictAlreadyActiveDetail,
      fetchStream,
      signal,
      onEvent,
      interceptEvent,
    })

    if (signal.aborted) {
      return 'aborted'
    }
    if (result === 'conflict_exhausted') {
      return result
    }
    if (!hasPending()) {
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
