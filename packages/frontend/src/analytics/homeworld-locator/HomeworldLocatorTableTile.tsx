import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useShellStore } from '../../stores/shell'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
} from './constants'
import { fetchHomeworldLocatorTable } from './api'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'

const EMPTY_ROSTER: readonly PerspectiveRow[] = []

type HomeworldLocatorTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

/**
 * Tabular candidate rows for Homeworld locator -- read-only mirror of the sidebar panel.
 */
export function HomeworldLocatorTableTile({
  analyticScope,
  fetchEnabled,
}: HomeworldLocatorTableTileProps) {
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const roster = perspectives ?? EMPTY_ROSTER
  const selection = useHomeworldLocatorSelectionStore((s) => s.selection)
  const setSelection = useHomeworldLocatorSelectionStore((s) => s.setSelection)
  const selectedPlanetId = selection?.kind === 'planet' ? selection.planetId : null

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
    <HomeworldCandidateRows
      rows={rows}
      baselineDegraded={data.baselineDegraded}
      baselineTurn={data.baselineTurn}
      mode="readOnly"
      roster={roster}
      selectedPlanetId={selectedPlanetId}
      onSelectPlanet={(planetId) => setSelection({ kind: 'planet', planetId })}
    />
  )
}
