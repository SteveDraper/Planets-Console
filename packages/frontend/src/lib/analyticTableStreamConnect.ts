import type { AnalyticShellScope } from '../api/bff'

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

export type AnalyticTableStreamConnectResult = 'ok' | 'aborted' | 'incomplete_exhausted'

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
    fetchStream: FetchAnalyticTableStream<TEvent>
    signal: AbortSignal
    onEvent: (event: TEvent) => void
    interceptEvent?: (event: TEvent, scope: AnalyticShellScope) => void
  }
): Promise<AnalyticTableStreamConnectResult> {
  const { fetchStream, signal, onEvent, interceptEvent } = options

  if (signal.aborted) {
    return 'aborted'
  }

  try {
    await fetchStream(scope, playerIds, {
      signal,
      onEvent: (event) => {
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
  return 'ok'
}

export async function connectAnalyticTableStreamUntilComplete<TEvent extends StreamErrorEvent>(
  scope: AnalyticShellScope,
  playerIds: number[],
  options: {
    fetchStream: FetchAnalyticTableStream<TEvent>
    signal: AbortSignal
    onEvent: (event: TEvent) => void
    hasPending: () => boolean
    interceptEvent?: (event: TEvent, scope: AnalyticShellScope) => void
    onBeforeIncompleteRetries?: (scope: AnalyticShellScope) => void
  }
): Promise<AnalyticTableStreamConnectResult> {
  const {
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

    await connectAnalyticTableStream(scope, playerIds, {
      fetchStream,
      signal,
      onEvent,
      interceptEvent,
    })

    if (signal.aborted) {
      return 'aborted'
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
