import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import {
  CONFIDENCE_DEFINITE,
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldBaselineDegradedMessage,
  homeworldInactiveHint,
} from './constants'
import { fetchHomeworldLocatorTable } from './api'
import type { HomeworldCandidateRecord } from './wireSchema'

type HomeworldLocatorTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

function confidenceLabel(row: HomeworldCandidateRecord): string {
  if (row.confidenceTier === CONFIDENCE_DEFINITE) return 'Definite'
  if (row.isMostProbable) return 'Possible (most probable)'
  return 'Possible'
}

function slotLabel(perspective: number | null): string {
  return perspective == null ? 'Orphan' : `Slot ${perspective}`
}

/**
 * Tabular candidate rows for Homeworld locator, including baseline-degraded note.
 */
export function HomeworldLocatorTableTile({
  analyticScope,
  fetchEnabled,
}: HomeworldLocatorTableTileProps) {
  const { data, isPending, error } = useQuery({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'table', analyticScope] as const,
    queryFn: () => fetchHomeworldLocatorTable(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
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
  if (data == null) return null

  if (!data.available) {
    return (
      <div className="p-4 text-sm text-slate-400">
        {homeworldInactiveHint(data.inactiveReason ?? null)}
      </div>
    )
  }

  const rows = data.rows ?? []

  return (
    <div className="flex flex-col gap-2 p-2">
      {data.baselineDegraded ? (
        <p className="px-2 text-xs text-amber-300/90" role="status">
          {homeworldBaselineDegradedMessage(data.baselineTurn)}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <div className="px-2 py-2 text-sm text-slate-400">No homeworld candidates inferred.</div>
      ) : (
        <div className="overflow-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-[#52575d]">
                <th className="px-3 py-2 text-left font-medium text-slate-200">Planet</th>
                <th className="px-3 py-2 text-left font-medium text-slate-200">Slot</th>
                <th className="px-3 py-2 text-left font-medium text-slate-200">Confidence</th>
                <th className="px-3 py-2 text-left font-medium text-slate-200">Attribution</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${row.planetId}-${row.perspective ?? 'orphan'}-${row.confidenceTier}`}
                  className="border-b border-[#52575d]/60"
                >
                  <td className="px-3 py-2 text-slate-200 tabular-nums">{row.planetId}</td>
                  <td className="px-3 py-2 text-slate-300">{slotLabel(row.perspective)}</td>
                  <td className="px-3 py-2 text-slate-300">{confidenceLabel(row)}</td>
                  <td className="px-3 py-2 text-slate-400">{row.attribution}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
