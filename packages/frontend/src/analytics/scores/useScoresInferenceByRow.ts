import { useMemo } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import {
  usePerPlayerAnalyticStream,
  type PerPlayerAnalyticStreamPolicy,
} from '../../lib/usePerPlayerAnalyticStream'
import { stablePlayerIdsKey } from '../../lib/stablePlayerIdsKey'
import type { UseGlobalInferencePauseResult } from './useGlobalInferencePause'
import {
  failureDetail,
  initialRowStreamState,
  reduceRowStreamState,
  rowDetailFromStreamState,
  withTablePause,
  type RowStreamState,
} from './inferenceRowStreamState'
import { connectTableInferenceStreamUntilComplete } from './tableInferenceStreamConnect'

/**
 * The table-level pause the rows read and the stream writes: every incomplete row
 * shows paused while `isGloballyPaused` is true, and `syncPausedFromStream`
 * receives each `globalPause` stream event, and false when the stream ends.
 */
export type ScoresInferenceTablePause = Pick<
  UseGlobalInferencePauseResult,
  'isGloballyPaused' | 'syncPausedFromStream'
>

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
}

function createScoresInferenceStreamPolicy(
  syncPausedFromStream: ScoresInferenceTablePause['syncPausedFromStream']
): PerPlayerAnalyticStreamPolicy<
  InferenceStreamEvent,
  RowStreamState,
  ScoresInferenceRowDetail
> {
  return {
    initialRefState: () => initialRowStreamState(),
    reduceRefState: (current, event) => reduceRowStreamState(current, event),
    isRefStateComplete: (state) => state.isStreamSettled,
    publishedFromRefState: (playerId, state) => rowDetailFromStreamState(playerId, state),
    seedPublishedOnNewConnection: (playerIds) => {
      const initialDetails = new Map<number, ScoresInferenceRowDetail>()
      for (const playerId of playerIds) {
        initialDetails.set(playerId, rowDetailFromStreamState(playerId, initialRowStreamState()))
      }
      return initialDetails
    },
    streamFailureEvent: (playerId, summary) => ({
      type: 'error',
      playerId,
      detail: summary,
    }),
    routeStreamEvent: (event) => {
      if (event.type === 'globalPause') {
        syncPausedFromStream(event.paused)
        return true
      }
      return false
    },
    onConnectionCleared: () => {
      syncPausedFromStream(false)
    },
    onConnectionTeardown: () => {
      syncPausedFromStream(false)
    },
    connectUntilComplete: (scope, playerIds, handlers) =>
      connectTableInferenceStreamUntilComplete(scope, playerIds, {
        signal: handlers.signal,
        onEvent: handlers.onEvent,
        hasPendingRows: handlers.hasPending,
      }),
    incompleteExhaustedMessage:
      'Build inference stream ended before all scoreboard rows completed.',
  }
}

export function useScoresInferenceByRow(
  tableData: TableDataResponse | undefined,
  scope: AnalyticShellScope | null,
  enabled: boolean,
  tablePause: ScoresInferenceTablePause
): UseScoresInferenceByRowResult {
  const { isGloballyPaused, syncPausedFromStream } = tablePause
  const inferenceByRowStubs = tableData?.inferenceByRow

  const playerIdsKey = useMemo(() => {
    if (!enabled || inferenceByRowStubs == null) {
      return ''
    }
    const playerIds = inferenceByRowStubs
      .map((stub) => stub.playerId)
      .filter((id): id is number => typeof id === 'number')
    return stablePlayerIdsKey(playerIds)
  }, [enabled, inferenceByRowStubs])

  // usePerPlayerAnalyticStream routes events, publishes and tears down through
  // the latest policy, so a new callback reaches those paths without reconnecting;
  // the open connection's connect, completion and failure handling keep the policy
  // it started with.
  const policy = useMemo(
    () => createScoresInferenceStreamPolicy(syncPausedFromStream),
    [syncPausedFromStream]
  )

  const { publishedByPlayerId: detailsByPlayerId } = usePerPlayerAnalyticStream({
    streamId: 'scores',
    scope,
    enabled,
    playerIdsKey,
    policy,
  })

  if (!enabled || tableData?.inferenceByRow == null) {
    return { inferenceByRow: undefined }
  }

  const inferenceByRow = tableData.inferenceByRow.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    return withTablePause(
      detailsByPlayerId.get(playerId) ??
        rowDetailFromStreamState(playerId, initialRowStreamState()),
      isGloballyPaused
    )
  })

  return { inferenceByRow }
}
