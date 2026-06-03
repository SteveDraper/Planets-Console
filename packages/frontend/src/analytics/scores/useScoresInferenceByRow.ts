import { useQueries } from '@tanstack/react-query'
import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import { fetchScoresRowInference } from '../../api/bff'
import { scoresRowInferenceQueryKey } from './api'
import { errorDetailFromUnknown } from '../../lib/queryRetry'

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

export function useScoresInferenceByRow(
  tableData: TableDataResponse | undefined,
  scope: AnalyticShellScope | null,
  enabled: boolean
): ScoresInferenceRowDetail[] | undefined {
  const stubs =
    enabled && tableData?.inferenceByRow != null ? tableData.inferenceByRow : []
  const playerIds = stubs
    .map((stub) => stub.playerId)
    .filter((id): id is number => typeof id === 'number')

  const queries = useQueries({
    queries: playerIds.map((playerId) => ({
      queryKey: scoresRowInferenceQueryKey(scope!, playerId),
      queryFn: () => fetchScoresRowInference(scope!, playerId),
      enabled: enabled && scope != null,
    })),
  })

  const queryByPlayerId = new Map(
    playerIds.map((playerId, index) => [playerId, queries[index]])
  )

  if (!enabled || tableData?.inferenceByRow == null) {
    return undefined
  }

  return stubs.map((stub, rowIndex) => {
    const playerId = stub.playerId
    if (typeof playerId !== 'number') {
      return failureDetail(-(rowIndex + 1), 'Missing player id for build inference')
    }
    const query = queryByPlayerId.get(playerId)
    if (query == null) {
      return pendingDetail(playerId)
    }
    if (query.isPending) {
      return pendingDetail(playerId)
    }
    if (query.isError) {
      return failureDetail(playerId, errorDetailFromUnknown(query.error))
    }
    if (query.data != null) {
      return query.data
    }
    return pendingDetail(playerId)
  })
}
