import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { errorDetailFromUnknown, parseHttpStatusFromErrorMessage } from '../../lib/queryRetry'
import { useScoresInferenceRevision } from '../../stores/scoresInferenceRevision'
import { fleetTableQueryKey } from './fleetTableQueryKey'

const FLEET_CONFLICT_REFETCH_DEBOUNCE_MS = 300

function isFleetGapFillConflictError(error: unknown): boolean {
  return parseHttpStatusFromErrorMessage(errorDetailFromUnknown(error)) === 409
}

export function useFleetTableQuery(
  analyticScope: AnalyticShellScope | null,
  fetchEnabled: boolean
) {
  const inferenceRevision = useScoresInferenceRevision(analyticScope)
  const previousInferenceRevisionRef = useRef(inferenceRevision)

  const query = useQuery({
    queryKey: fleetTableQueryKey(analyticScope),
    queryFn: () => fetchAnalyticTable('fleet', analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })

  useEffect(() => {
    if (!fetchEnabled || analyticScope == null) {
      previousInferenceRevisionRef.current = inferenceRevision
      return
    }
    if (inferenceRevision === previousInferenceRevisionRef.current) {
      return
    }
    previousInferenceRevisionRef.current = inferenceRevision
    if (!query.isError || !isFleetGapFillConflictError(query.error) || query.isFetching) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      void query.refetch()
    }, FLEET_CONFLICT_REFETCH_DEBOUNCE_MS)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [
    analyticScope,
    fetchEnabled,
    inferenceRevision,
    query.error,
    query.isError,
    query.isFetching,
    query.refetch,
  ])

  return query
}
