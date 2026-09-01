import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../api/bff'
import type { AnalyticShellScope } from '../api/bff'
import { errorDetailFromUnknown } from '../lib/queryRetry'
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

  if (isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (error) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {errorDetailFromUnknown(error)}
      </div>
    )
  }
  if (!data) return null
  if (!Array.isArray(data.columns) || !Array.isArray(data.rows)) {
    return (
      <div className="p-4 text-sm text-gray-400">This analytic has no tabular grid view.</div>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-[#52575d]">
            {data.columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-medium text-slate-200">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-b border-[#52575d]/60">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-gray-400">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
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
