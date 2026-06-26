import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { FleetTableView } from './FleetTableView'
import { parseFleetTableWire } from './fleetTableWireSchema'

type FleetAnalyticTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

export function FleetAnalyticTableTile({
  analyticScope,
  fetchEnabled,
}: FleetAnalyticTableTileProps) {
  const { data, isPending, error } = useQuery({
    queryKey: ['analytic', 'fleet', 'table', analyticScope] as const,
    queryFn: () => fetchAnalyticTable('fleet', analyticScope!),
    enabled: fetchEnabled,
  })

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }
  if (isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (error) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {errorDetailFromUnknown(error)}
      </div>
    )
  }
  if (!data) return null

  try {
    const fleetTable = parseFleetTableWire(data)
    return <FleetTableView data={fleetTable} />
  } catch (parseError) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading fleet table.{' '}
        {parseError instanceof Error ? parseError.message : String(parseError)}
      </div>
    )
  }
}
