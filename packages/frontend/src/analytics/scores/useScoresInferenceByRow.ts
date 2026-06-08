import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AnalyticShellScope,
  ScoresInferenceRowDetail,
  ScoresInferenceSolution,
  TableDataResponse,
} from '../../api/bff'
import { fetchScoresRowInferenceStream } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { admitInferenceSolution } from './inferenceHeldTopK'

function pendingDetail(playerId: number): ScoresInferenceRowDetail {
  return {
    playerId,
    displayStatus: 'pending',
    status: 'pending',
    summary: 'Build inference in progress',
    solutionCount: 0,
    isComplete: false,
    solutions: [],
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
  haltRow: (playerId: number) => void
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
  const abortControllersRef = useRef<Map<number, AbortController>>(new Map())

  const haltRow = useCallback((playerId: number) => {
    abortControllersRef.current.get(playerId)?.abort()
  }, [])

  useEffect(() => {
    if (!enabled || scope == null || playerIds.length === 0) {
      setDetailsByPlayerId(new Map())
      return
    }

    const controllers = new Map<number, AbortController>()
    abortControllersRef.current = controllers

    for (const playerId of playerIds) {
      const controller = new AbortController()
      controllers.set(playerId, controller)

      setDetailsByPlayerId((previous) => {
        const next = new Map(previous)
        next.set(playerId, pendingDetail(playerId))
        return next
      })

      let heldSolutions: ScoresInferenceSolution[] = []
      let status = 'pending'
      let summary = 'Build inference in progress'
      let isComplete = false
      let diagnostics: Record<string, unknown> = {}

      const publish = () => {
        setDetailsByPlayerId((previous) => {
          const next = new Map(previous)
          next.set(
            playerId,
            rowDetailFromStreamState(
              playerId,
              heldSolutions,
              status,
              summary,
              isComplete,
              diagnostics
            )
          )
          return next
        })
      }

      void fetchScoresRowInferenceStream(scope, playerId, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'solution') {
            heldSolutions = admitInferenceSolution(heldSolutions, event.solution)
            publish()
            return
          }
          if (event.type === 'complete') {
            status = event.status
            summary = event.summary
            isComplete = event.isComplete
            diagnostics = event.diagnostics ?? {}
            publish()
            return
          }
          if (event.type === 'error') {
            status = 'fetch_error'
            summary = event.detail
            isComplete = true
            publish()
          }
        },
      }).catch((error) => {
        if (controller.signal.aborted) {
          status = 'stopped'
          summary =
            heldSolutions.length > 0
              ? `Halted with ${heldSolutions.length} held solution(s)`
              : 'Build inference halted'
          isComplete = true
          publish()
          return
        }
        setDetailsByPlayerId((previous) => {
          const next = new Map(previous)
          next.set(playerId, failureDetail(playerId, errorDetailFromUnknown(error)))
          return next
        })
      })
    }

    return () => {
      for (const controller of controllers.values()) {
        controller.abort()
      }
      abortControllersRef.current = new Map()
    }
  }, [enabled, scope, playerIds.join(',')])

  if (!enabled || tableData?.inferenceByRow == null) {
    return { inferenceByRow: undefined, haltRow }
  }

  const inferenceByRow = stubs.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    return detailsByPlayerId.get(playerId) ?? pendingDetail(playerId)
  })

  return { inferenceByRow, haltRow }
}
