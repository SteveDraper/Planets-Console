import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AnalyticShellScope,
  ScoresInferenceRowDetail,
  ScoresInferenceSolution,
  TableDataResponse,
} from '../../api/bff'
import {
  fetchScoresRowInferenceStream,
  fetchScoresTableInferenceStream,
  stopScoresRowInference,
} from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import { errorDetailFromUnknown } from '../../lib/queryRetry'

function pendingDetail(
  playerId: number,
  solutions: ScoresInferenceSolution[] = []
): ScoresInferenceRowDetail {
  return {
    playerId,
    displayStatus: solutions.length > 0 ? 'success' : 'pending',
    status: 'pending',
    summary: 'Build inference in progress',
    solutionCount: solutions.length,
    isComplete: false,
    solutions,
    diagnostics: {},
  }
}

function failureDetail(playerId: number, summary: string): ScoresInferenceRowDetail {
  return {
    playerId,
    displayStatus: 'failure',
    status: 'fetch_error',
    summary,
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: {},
  }
}

function displayStatusForRow(
  status: string,
  solutionCount: number,
  isComplete: boolean
): ScoresInferenceRowDetail['displayStatus'] {
  if (status === 'paused') {
    return 'paused'
  }
  if (status === 'stopped') {
    return solutionCount > 0 ? 'success' : 'stopped'
  }
  if (solutionCount > 0 && !isComplete) {
    return 'success'
  }
  if (status === 'exact' || (solutionCount > 0 && isComplete)) {
    return 'success'
  }
  if (!isComplete) {
    return 'pending'
  }
  return 'failure'
}

function rowDetailFromStreamState(
  playerId: number,
  solutions: ScoresInferenceSolution[],
  status: string,
  summary: string,
  isComplete: boolean,
  diagnostics: Record<string, unknown>
): ScoresInferenceRowDetail {
  const solutionCount = solutions.length
  return {
    playerId,
    displayStatus: displayStatusForRow(status, solutionCount, isComplete),
    status,
    summary,
    solutionCount,
    isComplete,
    solutions,
    diagnostics,
  }
}

export type UseScoresInferenceByRowResult = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
  stopRow: (playerId: number) => void
  resumeRow: (playerId: number) => void
}

function pausedSummaryFromSolutions(solutions: ScoresInferenceSolution[]): string {
  return solutions.length > 0
    ? `Paused with ${solutions.length} held solution(s)`
    : 'Build inference paused'
}

type RowStreamState = {
  heldSolutions: ScoresInferenceSolution[]
  status: string
  summary: string
  isComplete: boolean
  diagnostics: Record<string, unknown>
}

function initialRowStreamState(
  carryOverSolutions: ScoresInferenceSolution[] = []
): RowStreamState {
  return {
    heldSolutions: [...carryOverSolutions],
    status: 'pending',
    summary: 'Build inference in progress',
    isComplete: false,
    diagnostics: {},
  }
}

export function useScoresInferenceByRow(
  tableData: TableDataResponse | undefined,
  scope: AnalyticShellScope | null,
  enabled: boolean
): UseScoresInferenceByRowResult {
  const stubs =
    enabled && tableData?.inferenceByRow != null ? tableData.inferenceByRow : []
  const playerIds = stubs
    .map((stub) => stub.playerId)
    .filter((id): id is number => typeof id === 'number')

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
      next.set(
        playerId,
        rowDetailFromStreamState(
          playerId,
          state.heldSolutions,
          state.status,
          state.summary,
          state.isComplete,
          state.diagnostics
        )
      )
      return next
    })
  }, [])

  const applyStreamEvent = useCallback(
    (playerId: number, event: InferenceStreamEvent) => {
      let state = rowStreamStateRef.current.get(playerId)
      if (state == null) {
        state = initialRowStreamState()
        rowStreamStateRef.current.set(playerId, state)
      }

      if (event.type === 'globalPause') {
        if (event.paused && !state.isComplete) {
          state.status = 'paused'
          state.summary = pausedSummaryFromSolutions(state.heldSolutions)
        } else if (!event.paused && state.status === 'paused') {
          state.status = 'pending'
          state.summary = 'Build inference in progress'
        }
        publishPlayerState(playerId)
        return
      }

      if (event.type === 'progress') {
        if (!state.isComplete) {
          state.summary = event.policyStepId
            ? `Searching (${event.policyStepId.replace(/_/g, ' ')})`
            : 'Build inference in progress'
        }
        publishPlayerState(playerId)
        return
      }

      if (event.type === 'solution') {
        state.heldSolutions = event.solutions
        publishPlayerState(playerId)
        return
      }

      if (event.type === 'complete') {
        state.status = event.status
        state.summary = event.summary
        state.isComplete = event.isComplete
        state.diagnostics = event.diagnostics ?? {}
        publishPlayerState(playerId)
        return
      }

      if (event.type === 'error') {
        state.status = 'fetch_error'
        state.summary = event.detail
        state.isComplete = true
        publishPlayerState(playerId)
      }
    },
    [publishPlayerState]
  )

  const applyGlobalPauseEvent = useCallback(
    (event: Extract<InferenceStreamEvent, { type: 'globalPause' }>) => {
      for (const playerId of rowStreamStateRef.current.keys()) {
        applyStreamEvent(playerId, event)
      }
    },
    [applyStreamEvent]
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
    (playerId: number, carryOverSolutions: ScoresInferenceSolution[] = []) => {
      if (scope == null) {
        return
      }

      resumeAbortControllersRef.current.get(playerId)?.abort()
      const controller = new AbortController()
      resumeAbortControllersRef.current.set(playerId, controller)
      independentResumePlayersRef.current.add(playerId)

      rowStreamStateRef.current.set(playerId, initialRowStreamState(carryOverSolutions))
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
            const state = rowStreamStateRef.current.get(playerId)
            if (state != null && !state.isComplete) {
              state.status = 'paused'
              state.summary = pausedSummaryFromSolutions(state.heldSolutions)
              publishPlayerState(playerId)
            }
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

  const stopRow = useCallback(
    (playerId: number) => {
      if (independentResumePlayersRef.current.has(playerId)) {
        resumeAbortControllersRef.current.get(playerId)?.abort()
        return
      }
      if (scope == null) {
        return
      }
      void stopScoresRowInference(scope, playerId).catch(() => {
        // Row stop is best-effort; stream complete event is authoritative.
      })
    },
    [scope]
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
          next.set(
            playerId,
            failureDetail(playerId, errorDetailFromUnknown(error))
          )
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
  }, [enabled, scope, playerIds.join(','), handleTableStreamEvent])

  if (!enabled || tableData?.inferenceByRow == null) {
    return { inferenceByRow: undefined, stopRow, resumeRow }
  }

  const inferenceByRow = stubs.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    return detailsByPlayerId.get(playerId) ?? pendingDetail(playerId)
  })

  return { inferenceByRow, stopRow, resumeRow }
}
