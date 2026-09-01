import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../api/bff'
import type { AnalyticShellScope } from '../api/bff'
import { AnalyticTableGrid } from './AnalyticTableGrid'
import type { ShellAnalyticTableViewProps } from './shellAnalyticRegistry'

function GenericAnalyticTableGrid({
  analyticId,
  analyticScope,
  fetchEnabled,
}: {
  analyticId: string
  analyticScope: AnalyticShellScope
  fetchEnabled: boolean
}) {
  const { data, isPending, error } = useQuery({
    queryKey: ['analytic', analyticId, 'table', analyticScope] as const,
    queryFn: () => fetchAnalyticTable(analyticId, analyticScope),
    enabled: fetchEnabled,
  })

  return <AnalyticTableGrid isPending={isPending} error={error} data={data} />
}

/** Default MainArea table body when no custom TableView is registered. */
export function GenericTableTile({
  analyticId,
  analyticScope,
  fetchEnabled,
}: ShellAnalyticTableViewProps) {
  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }
  return (
    <GenericAnalyticTableGrid
      analyticId={analyticId}
      analyticScope={analyticScope}
      fetchEnabled={fetchEnabled}
    />
  )
}
