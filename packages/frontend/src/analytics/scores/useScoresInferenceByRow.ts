import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import {
  failureDetail,
  initialRowStreamState,
  pendingDetail,
  playerIdsFromStableKey,
  reduceRowStreamState,
  rowDetailFromStreamState,
  stableAnalyticScopeKey,
  stablePlayerIdsKey,
  type RowStreamState,
} from './inferenceRowStreamState'
import { connectTableInferenceStream } from './tableInferenceStreamConnect'

export type UseScoresInferenceByRowOptions = {
  onGlobalPauseChange?: (paused: boolean) => void
}

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
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
  const scopeKey = scope != null ? stableAnalyticScopeKey(scope) : null
  const connectionKey =
    enabled && scopeKey != null && playerIdsKey.length > 0 ? `${scopeKey}:${playerIdsKey}` : null

  const [detailsByPlayerId, setDetailsByPlayerId] = useState<
    Map<number, ScoresInferenceRowDetail>
  >(new Map())
  const tableAbortControllerRef = useRef<AbortController | null>(null)
  const rowStreamStateRef = useRef<Map<number, RowStreamState>>(new Map())
  const connectionKeyRef = useRef<string | null>(null)
  const scopeRef = useRef(scope)
  scopeRef.current = scope

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
  const handleTableStreamEventRef = useRef(handleTableStreamEvent)
  handleTableStreamEventRef.current = handleTableStreamEvent
  const onGlobalPauseChangeRef = useRef(onGlobalPauseChange)
  onGlobalPauseChangeRef.current = onGlobalPauseChange

  useEffect(() => {
    if (connectionKey == null) {
      connectionKeyRef.current = null
      setDetailsByPlayerId(new Map())
      rowStreamStateRef.current = new Map()
      onGlobalPauseChangeRef.current?.(false)
      return
    }

    const activeScope = scopeRef.current
    if (activeScope == null) {
      return
    }

    const isNewConnection = connectionKeyRef.current !== connectionKey
    connectionKeyRef.current = connectionKey
    const playerIds = playerIdsFromStableKey(playerIdsKey)

    tableAbortControllerRef.current?.abort()

    if (isNewConnection) {
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
    }

    const controller = new AbortController()
    tableAbortControllerRef.current = controller

    void connectTableInferenceStream(activeScope, playerIds, {
      signal: controller.signal,
      onEvent: (event) => handleTableStreamEventRef.current(event),
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
                'Build inference could not reconnect to the table stream.'
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
      onGlobalPauseChangeRef.current?.(false)
    }
  }, [connectionKey, playerIdsKey])

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
