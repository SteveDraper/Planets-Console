import { useMemo, useRef, type MutableRefObject } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import {
  usePerPlayerAnalyticStream,
  type PerPlayerAnalyticStreamPolicy,
} from '../../lib/usePerPlayerAnalyticStream'
import { stablePlayerIdsKey } from '../../lib/stablePlayerIdsKey'
import {
  failureDetail,
  initialRowStreamState,
  reduceRowStreamState,
  rowDetailFromStreamState,
  withTablePause,
  type RowStreamState,
} from './inferenceRowStreamState'
import { connectTableInferenceStreamUntilComplete } from './tableInferenceStreamConnect'

export type UseScoresInferenceByRowOptions = {
  /** Called with each `globalPause` stream event, and with false when the stream ends. */
  onGlobalPauseChange?: (paused: boolean) => void
  /** The table-level pause; every incomplete row shows paused while it is true. */
  isGloballyPaused?: boolean
}

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
}

function createScoresInferenceStreamPolicy(
  onGlobalPauseChangeRef: MutableRefObject<((paused: boolean) => void) | undefined>
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
        onGlobalPauseChangeRef.current?.(event.paused)
        return true
      }
      return false
    },
    onConnectionCleared: () => {
      onGlobalPauseChangeRef.current?.(false)
    },
    onConnectionTeardown: () => {
      onGlobalPauseChangeRef.current?.(false)
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
  options: UseScoresInferenceByRowOptions = {}
): UseScoresInferenceByRowResult {
  const { onGlobalPauseChange, isGloballyPaused = false } = options
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

  const onGlobalPauseChangeRef = useRef(onGlobalPauseChange)
  onGlobalPauseChangeRef.current = onGlobalPauseChange

  const policy = useMemo(
    () => createScoresInferenceStreamPolicy(onGlobalPauseChangeRef),
    []
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
