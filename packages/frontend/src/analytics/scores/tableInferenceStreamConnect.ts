import type { AnalyticShellScope } from '../../api/bff'
import { fetchScoresTableInferenceStream } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import { bumpScoresInferenceRevision } from '../../shell/scoresInferenceRevision'

export const TABLE_STREAM_ALREADY_ACTIVE_DETAIL =
  'An inference table stream is already active for this scope.'

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

function isScopeLevelStreamConflict(event: InferenceStreamEvent): boolean {
  return (
    event.type === 'error' &&
    event.playerId == null &&
    event.detail === TABLE_STREAM_ALREADY_ACTIVE_DETAIL
  )
}

function shouldBumpScoresInferenceRevision(event: InferenceStreamEvent): boolean {
  return event.type === 'solution' || event.type === 'complete'
}

export type TableInferenceStreamConnectResult =
  | 'ok'
  | 'aborted'
  | 'conflict_exhausted'
  | 'incomplete_exhausted'

export async function connectTableInferenceStream(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: InferenceStreamEvent) => void
  }
): Promise<TableInferenceStreamConnectResult> {
  for (let attempt = 0; attempt < STREAM_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (handlers.signal.aborted) {
      return 'aborted'
    }

    let scopeConflict = false

    try {
      await fetchScoresTableInferenceStream(scope, playerIds, {
        signal: handlers.signal,
        onEvent: (event) => {
          if (isScopeLevelStreamConflict(event)) {
            scopeConflict = true
            return
          }
          if (shouldBumpScoresInferenceRevision(event)) {
            bumpScoresInferenceRevision(scope)
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

export async function connectTableInferenceStreamUntilComplete(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: InferenceStreamEvent) => void
    hasPendingRows: () => boolean
  }
): Promise<TableInferenceStreamConnectResult> {
  for (let attempt = 0; attempt < STREAM_INCOMPLETE_RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (handlers.signal.aborted) {
      return 'aborted'
    }

    const result = await connectTableInferenceStream(scope, playerIds, {
      signal: handlers.signal,
      onEvent: handlers.onEvent,
    })

    if (handlers.signal.aborted) {
      return 'aborted'
    }
    if (result === 'conflict_exhausted') {
      return result
    }
    if (!handlers.hasPendingRows()) {
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
