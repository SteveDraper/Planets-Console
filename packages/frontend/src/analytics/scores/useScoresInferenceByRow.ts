import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import {
  fetchScoresRowInferenceStream,
  fetchScoresTableInferenceStream,
} from '../../api/bff'
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

export type UseScoresInferenceByRowOptions = {
  onGlobalPauseChange?: (paused: boolean) => void
}

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
  resumeRow: (playerId: number) => void
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

  const [detailsByPlayerId, setDetailsByPlayerId] = useState<
    Map<number, ScoresInferenceRowDetail>
  >(new Map())
  const detailsByPlayerIdRef = useRef(detailsByPlayerId)
  detailsByPlayerIdRef.current = detailsByPlayerId

  const tableAbortControllerRef = useRef<AbortController | null>(null)
  const resumeAbortControllersRef = useRef<Map<number, AbortController>>(new Map())
  const independentResumePlayersRef = useRef<Set<number>>(new Set())
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
      const playerId = 'playerId' in event ? event.playerId : undefined
      if (typeof playerId !== 'number') {
        return
      }
      if (independentResumePlayersRef.current.has(playerId)) {
        return
      }
      applyStreamEvent(playerId, event)
    },
    [applyGlobalPauseEvent, applyStreamEvent]
  )

  const startStreamForPlayer = useCallback(
    (playerId: number, carryOverSolutions: ScoresInferenceRowDetail['solutions'] = []) => {
      if (scope == null) {
        return
      }

      resumeAbortControllersRef.current.get(playerId)?.abort()
      const controller = new AbortController()
      resumeAbortControllersRef.current.set(playerId, controller)
      independentResumePlayersRef.current.add(playerId)

      rowStreamStateRef.current.set(
        playerId,
        initialRowStreamState(carryOverSolutions ?? [])
      )
      publishPlayerState(playerId)

      void fetchScoresRowInferenceStream(scope, playerId, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'globalPause') {
            applyGlobalPauseEvent(event)
            return
          }
          applyStreamEvent(playerId, event)
        },
      })
        .catch((error) => {
          if (controller.signal.aborted) {
            return
          }
          setDetailsByPlayerId((previous) => {
            const next = new Map(previous)
            next.set(playerId, failureDetail(playerId, errorDetailFromUnknown(error)))
            return next
          })
        })
        .finally(() => {
          resumeAbortControllersRef.current.delete(playerId)
          independentResumePlayersRef.current.delete(playerId)
        })
    },
    [scope, applyGlobalPauseEvent, applyStreamEvent, publishPlayerState]
  )

  const resumeRow = useCallback(
    (playerId: number) => {
      const detail = detailsByPlayerIdRef.current.get(playerId)
      const carryOver =
        detail?.displayStatus === 'paused' || detail?.displayStatus === 'stopped'
          ? detail.solutions
          : []
      startStreamForPlayer(playerId, carryOver)
    },
    [startStreamForPlayer]
  )

  useEffect(() => {
    if (!enabled || scope == null || playerIds.length === 0) {
      setDetailsByPlayerId(new Map())
      rowStreamStateRef.current = new Map()
      return
    }

    tableAbortControllerRef.current?.abort()
    for (const controller of resumeAbortControllersRef.current.values()) {
      controller.abort()
    }
    resumeAbortControllersRef.current = new Map()
    independentResumePlayersRef.current = new Set()

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

    void fetchScoresTableInferenceStream(scope, playerIds, {
      signal: controller.signal,
      onEvent: handleTableStreamEvent,
    }).catch((error) => {
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
      for (const resumeController of resumeAbortControllersRef.current.values()) {
        resumeController.abort()
      }
      resumeAbortControllersRef.current = new Map()
      independentResumePlayersRef.current = new Set()
    }
  }, [enabled, scope, playerIdsKey, handleTableStreamEvent])

  if (!enabled || tableData?.inferenceByRow == null) {
    return { inferenceByRow: undefined, resumeRow }
  }

  const inferenceByRow = stubs.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    return detailsByPlayerId.get(playerId) ?? pendingDetail(playerId)
  })

  return { inferenceByRow, resumeRow }
}
