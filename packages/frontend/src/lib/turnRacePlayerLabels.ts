import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable, type AnalyticShellScope, type TableDataResponse } from '../api/bff'
import { scoresTableQueryKey } from '../analytics/scores/api'

const SCORES_TABLE_LABELS_PARAMS = { includeBuildInference: false } as const

export function turnRacePlayerLabelsFromTable(
  data: TableDataResponse | undefined
): Map<number, string> {
  const labels = new Map<number, string>()
  if (data?.analyticId !== 'scores') {
    return labels
  }
  const playerIds = data.rowPlayerIds
  if (!Array.isArray(playerIds)) {
    return labels
  }
  for (let index = 0; index < data.rows.length; index += 1) {
    const playerId = playerIds[index]
    const row = data.rows[index]
    if (typeof playerId !== 'number' || !Array.isArray(row)) {
      continue
    }
    const label = row[0]
    if (typeof label === 'string' && label.trim() !== '') {
      labels.set(playerId, label)
    }
  }
  return labels
}

export function useTurnRacePlayerLabels(
  scope: AnalyticShellScope | null,
  enabled: boolean
): Map<number, string> {
  const { data } = useQuery({
    queryKey: [
      'analytic',
      'scores',
      'table',
      scope,
      ...scoresTableQueryKey(SCORES_TABLE_LABELS_PARAMS),
    ] as const,
    queryFn: () => fetchAnalyticTable('scores', scope!, SCORES_TABLE_LABELS_PARAMS),
    enabled: enabled && scope != null,
  })
  return useMemo(() => turnRacePlayerLabelsFromTable(data), [data])
}
