import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useShellStore } from '../../stores/shell'
import { useTeamInformationPreferencesStore } from '../../stores/teamInformationPreferences'
import { tileClassName } from '../tileChrome'
import { teamInformationLegendRows } from './teamLegend'
import { teamInformationMapQuerySpec } from './mapAnalytic'
import { useTurnRosterUsernames } from './useTurnRosterUsernames'
import { FillPatternMarks } from '../../lib/mapRegionFillPatternMarks'

type TeamInformationMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  analyticScope: AnalyticShellScope | null
  turnDataReady: boolean
}

function rosterUsernames(
  perspectives: readonly PerspectiveRow[],
  turnUsernames: ReadonlyMap<number, string> | null
): Map<number, string> {
  const usernames = new Map<number, string>()
  for (const row of perspectives) {
    const name = row.name.trim()
    if (name) usernames.set(row.playerId, name)
  }
  if (turnUsernames != null) {
    for (const [playerId, username] of turnUsernames) {
      const trimmed = username.trim()
      if (trimmed) usernames.set(playerId, trimmed)
    }
  }
  return usernames
}

export function TeamInformationMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  analyticScope,
  turnDataReady,
}: TeamInformationMapTileProps) {
  const ownedPlanetsOnly = useTeamInformationPreferencesStore((s) => s.ownedPlanetsOnly)
  const setOwnedPlanetsOnly = useTeamInformationPreferencesStore((s) => s.setOwnedPlanetsOnly)
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const turnUsernames = useTurnRosterUsernames(analyticScope)

  const fetchEnabled = supportsMode && enabled && turnDataReady
  const mapQuery = useQuery(teamInformationMapQuerySpec(analyticScope, fetchEnabled))

  const legendRows = useMemo(
    () =>
      teamInformationLegendRows(
        mapQuery.data?.teamInformationTeams ?? [],
        rosterUsernames(perspectives ?? [], turnUsernames)
      ),
    [mapQuery.data?.teamInformationTeams, perspectives, turnUsernames]
  )

  const showLegend = supportsMode && enabled && legendRows.length > 0

  return (
    <div
      className={cn(
        tileClassName({ supportsMode, depressed }),
        'flex min-w-0 max-w-full flex-col'
      )}
    >
      <label
        className={cn(
          'flex cursor-pointer items-center gap-2 px-2 py-1.5',
          !supportsMode && 'cursor-default'
        )}
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={() => supportsMode && onToggle()}
          disabled={!supportsMode}
          className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
        />
        <span className="min-w-0 truncate">{name}</span>
      </label>
      <label
        className={cn(
          'flex items-center gap-2 px-2 pb-1.5',
          supportsMode ? 'cursor-pointer' : 'cursor-default'
        )}
      >
        <input
          type="checkbox"
          checked={ownedPlanetsOnly}
          onChange={(event) => setOwnedPlanetsOnly(event.target.checked)}
          disabled={!supportsMode}
          className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
        />
        <span className="min-w-0 truncate text-xs text-slate-300">Owned planets only</span>
      </label>
      {showLegend ? (
        <ul aria-label="League teams" className="flex flex-col gap-1 border-t border-[#52575d]/40 px-2 py-2">
          {legendRows.map((row) => (
            <li key={row.leagueTeamId} className="flex min-w-0 items-start gap-2">
              <span
                aria-hidden
                data-fill-pattern={row.fillPattern}
                className="relative mt-0.5 h-3 w-3 shrink-0 overflow-hidden rounded-sm border border-black/30"
                style={{ backgroundColor: row.fillColor }}
              >
                {row.fillPattern === 'solid' ? null : (
                  <svg className="absolute inset-0 h-full w-full" viewBox="0 0 8 8">
                    <FillPatternMarks pattern={row.fillPattern} />
                  </svg>
                )}
              </span>
              <span className="min-w-0 text-xs text-slate-300">
                <span className="font-mono">{row.leagueTeamId}</span>
                {row.usernames.length > 0 ? (
                  <span className="text-slate-400"> {row.usernames.join(', ')}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
