import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { FleetTableView } from './FleetTableView'
import { parseFleetTableWire, type FleetTableWire } from './fleetTableWireSchema'

type FleetAnalyticTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

type FleetTableParseResult =
  | { ok: true; data: FleetTableWire }
  | { ok: false; error: string }

function parseFleetTableWireResult(payload: unknown): FleetTableParseResult {
  try {
    return { ok: true, data: parseFleetTableWire(payload) }
  } catch (parseError) {
    return {
      ok: false,
      error: parseError instanceof Error ? parseError.message : String(parseError),
    }
  }
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

  const parsedFleetTable = useMemo(
    () => (data != null ? parseFleetTableWireResult(data) : null),
    [data]
  )

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

  if (parsedFleetTable == null || !parsedFleetTable.ok) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading fleet table.{' '}
        {parsedFleetTable?.ok === false ? parsedFleetTable.error : 'Unknown parse error.'}
      </div>
    )
  }

  return <FleetTableView data={parsedFleetTable.data} />
}
