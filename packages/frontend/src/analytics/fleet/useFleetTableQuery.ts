import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { fleetTableQueryKey } from './fleetTableQueryKey'

export function useFleetTableQuery(
  analyticScope: AnalyticShellScope | null,
  fetchEnabled: boolean
) {
  return useQuery({
    queryKey: fleetTableQueryKey(analyticScope),
    queryFn: () => fetchAnalyticTable('fleet', analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
}
