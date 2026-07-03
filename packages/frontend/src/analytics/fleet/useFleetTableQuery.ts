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
  const revisionAtLastConflictRefetchRef = useRef<number | null>(null)

  const query = useQuery({
    queryKey: fleetTableQueryKey(analyticScope),
    queryFn: () => fetchAnalyticTable('fleet', analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })

  useEffect(() => {
    if (!fetchEnabled || analyticScope == null) {
      revisionAtLastConflictRefetchRef.current = null
      return
    }

    if (query.isSuccess) {
      revisionAtLastConflictRefetchRef.current = null
      return
    }

    if (!query.isError || !isFleetGapFillConflictError(query.error) || query.isFetching) {
      return
    }

    if (revisionAtLastConflictRefetchRef.current === inferenceRevision) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      revisionAtLastConflictRefetchRef.current = inferenceRevision
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
    query.isSuccess,
    query.refetch,
  ])

  return query
}
