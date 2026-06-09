import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import {
  failureDetail,
  initialRowStreamState,
  pendingDetail,
  reduceRowStreamState,
  rowDetailFromStreamState,
  stablePlayerIdsKey,
  type RowStreamState,
} from './inferenceRowStreamState'
import { connectTableInferenceStream } from './tableInferenceStreamConnect'

export type UseScoresInferenceByRowOptions = {
  onGlobalPauseChange?: (paused: boolean) => void
}

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
  refreshInference: () => void
}

export function useScoresInferenceByRow(
  tableData: TableDataResponse | undefined,
  scope: AnalyticShellScope | null,
  enabled: boolean,
  options: UseScoresInferenceByRowOptions = {}
): UseScoresInferenceByRowResult {
  const { onGlobalPauseChange } = options
  const stubs =
    enabled && tableData?.inferenceByRow != null ? tableData.inferenceByRow : []
  const playerIds = stubs
    .map((stub) => stub.playerId)
    .filter((id): id is number => typeof id === 'number')
  const playerIdsKey = useMemo(() => stablePlayerIdsKey(playerIds), [playerIds])
  const [refreshToken, setRefreshToken] = useState(0)
  const refreshInference = useCallback(() => {
    setRefreshToken((value) => value + 1)
  }, [])

  const [detailsByPlayerId, setDetailsByPlayerId] = useState<
    Map<number, ScoresInferenceRowDetail>
  >(new Map())
  const tableAbortControllerRef = useRef<AbortController | null>(null)
  const rowStreamStateRef = useRef<Map<number, RowStreamState>>(new Map())

  const publishPlayerState = useCallback((playerId: number) => {
    const state = rowStreamStateRef.current.get(playerId)
    if (state == null) {
      return
    }
    setDetailsByPlayerId((previous) => {
      const next = new Map(previous)
      next.set(playerId, rowDetailFromStreamState(playerId, state))
      return next
    })
  }, [])

  const applyStreamEvent = useCallback(
    (playerId: number, event: InferenceStreamEvent) => {
      const current = rowStreamStateRef.current.get(playerId) ?? initialRowStreamState()
      const next = reduceRowStreamState(current, event)
      rowStreamStateRef.current.set(playerId, next)
      publishPlayerState(playerId)
    },
    [publishPlayerState]
  )

  const applyGlobalPauseEvent = useCallback(
    (event: Extract<InferenceStreamEvent, { type: 'globalPause' }>) => {
      onGlobalPauseChange?.(event.paused)
      for (const playerId of rowStreamStateRef.current.keys()) {
        applyStreamEvent(playerId, event)
      }
    },
    [applyStreamEvent, onGlobalPauseChange]
  )

  const handleTableStreamEvent = useCallback(
    (event: InferenceStreamEvent) => {
      if (event.type === 'globalPause') {
        applyGlobalPauseEvent(event)
        return
      }
      if (event.type === 'error' && event.playerId == null) {
        for (const playerId of rowStreamStateRef.current.keys()) {
          applyStreamEvent(playerId, { ...event, playerId })
        }
        return
      }
      const playerId = 'playerId' in event ? event.playerId : undefined
      if (typeof playerId !== 'number') {
        return
      }
      applyStreamEvent(playerId, event)
    },
    [applyGlobalPauseEvent, applyStreamEvent]
  )

  useEffect(() => {
    if (!enabled || scope == null || playerIds.length === 0) {
      setDetailsByPlayerId(new Map())
      rowStreamStateRef.current = new Map()
      onGlobalPauseChange?.(false)
      return
    }

    tableAbortControllerRef.current?.abort()

    const initialStates = new Map<number, RowStreamState>()
    for (const playerId of playerIds) {
      initialStates.set(playerId, initialRowStreamState())
    }
    rowStreamStateRef.current = initialStates

    const initialDetails = new Map<number, ScoresInferenceRowDetail>()
    for (const playerId of playerIds) {
      initialDetails.set(playerId, pendingDetail(playerId))
    }
    setDetailsByPlayerId(initialDetails)

    const controller = new AbortController()
    tableAbortControllerRef.current = controller

    void connectTableInferenceStream(scope, playerIds, {
      signal: controller.signal,
      onEvent: handleTableStreamEvent,
    })
      .then((result) => {
        if (controller.signal.aborted || result !== 'conflict_exhausted') {
          return
        }
        setDetailsByPlayerId((previous) => {
          const next = new Map(previous)
          for (const playerId of playerIds) {
            if (next.get(playerId)?.isComplete) {
              continue
            }
            next.set(
              playerId,
              failureDetail(
                playerId,
                'Build inference could not reconnect after updating the hull catalog.'
              )
            )
          }
          return next
        })
      })
      .catch((error) => {
      if (controller.signal.aborted) {
        return
      }
      setDetailsByPlayerId((previous) => {
        const next = new Map(previous)
        for (const playerId of playerIds) {
          if (next.get(playerId)?.isComplete) {
            continue
          }
          next.set(playerId, failureDetail(playerId, errorDetailFromUnknown(error)))
        }
        return next
      })
    })

    return () => {
      controller.abort()
      tableAbortControllerRef.current = null
      onGlobalPauseChange?.(false)
    }
  }, [enabled, scope, playerIdsKey, refreshToken, handleTableStreamEvent, onGlobalPauseChange])

  if (!enabled || tableData?.inferenceByRow == null) {
    return { inferenceByRow: undefined, refreshInference }
  }

  const inferenceByRow = stubs.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    return detailsByPlayerId.get(playerId) ?? pendingDetail(playerId)
  })

  return { inferenceByRow, refreshInference }
}
