import { useQuery } from '@tanstack/react-query'
import { fetchFleetComponentCatalog } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import {
  EMPTY_FLEET_COMPONENT_CATALOG,
  type FleetComponentCatalog,
} from './fleetComponentCatalog'
import { fleetComponentCatalogQueryKey } from './fleetComponentCatalogQueryKey'

export function useFleetComponentCatalogQuery(
  analyticScope: AnalyticShellScope | null,
  fetchEnabled: boolean
): FleetComponentCatalog {
  const { data } = useQuery({
    queryKey: fleetComponentCatalogQueryKey(analyticScope),
    queryFn: () => fetchFleetComponentCatalog(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })

  return data ?? EMPTY_FLEET_COMPONENT_CATALOG
}
