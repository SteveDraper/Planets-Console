import { useMemo, useRef, type MutableRefObject } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import {
  usePerPlayerAnalyticStream,
  type PerPlayerAnalyticStreamPolicy,
} from '../../lib/usePerPlayerAnalyticStream'
import {
  failureDetail,
  initialRowStreamState,
  pendingDetail,
  reduceRowStreamState,
  rowDetailFromStreamState,
  stablePlayerIdsKey,
  type RowStreamState,
} from './inferenceRowStreamState'
import { connectTableInferenceStreamUntilComplete } from './tableInferenceStreamConnect'

export type UseScoresInferenceByRowOptions = {
  onGlobalPauseChange?: (paused: boolean) => void
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
    isRefStateComplete: (state) => state.isComplete,
    publishedFromRefState: (playerId, state) => rowDetailFromStreamState(playerId, state),
    seedPublishedOnNewConnection: (playerIds) => {
      const initialDetails = new Map<number, ScoresInferenceRowDetail>()
      for (const playerId of playerIds) {
        initialDetails.set(playerId, pendingDetail(playerId))
      }
      return initialDetails
    },
    markIncompleteFailed: (playerIds, previous, summary) => {
      const next = new Map(previous)
      for (const playerId of playerIds) {
        if (next.get(playerId)?.isComplete) {
          continue
        }
        next.set(playerId, failureDetail(playerId, summary))
      }
      return next
    },
    routeStreamEvent: (event, { applyToAllPlayers }) => {
      if (event.type === 'globalPause') {
        onGlobalPauseChangeRef.current?.(event.paused)
        applyToAllPlayers(event)
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
    conflictExhaustedMessage: 'Build inference could not reconnect to the table stream.',
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
  const { onGlobalPauseChange } = options
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
    return detailsByPlayerId.get(playerId) ?? pendingDetail(playerId)
  })

  return { inferenceByRow }
}
