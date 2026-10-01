import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useShellStore } from '../../stores/shell'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'
import { useTeamInformationPreferencesStore } from '../../stores/teamInformationPreferences'
import { AnalyticSidebarTile } from '../AnalyticSidebarTile'
import {
  teamInformationLegendHoverTitle,
  teamInformationLegendRows,
  teamInformationLegendText,
} from './teamLegend'
import { teamInformationMapQuerySpec } from './mapAnalytic'
import { useLeagueTeamNames } from './useLeagueTeamNames'
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
  const hiddenLeagueTeamIds = useTeamInformationPreferencesStore((s) => s.hiddenLeagueTeamIds)
  const setLeagueTeamRegionVisible = useTeamInformationPreferencesStore(
    (s) => s.setLeagueTeamRegionVisible
  )
  const setHoveredLeagueTeamId = useTeamInformationHighlightStore(
    (s) => s.setHoveredLeagueTeamId
  )
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const turnUsernames = useTurnRosterUsernames(analyticScope)

  const fetchEnabled = supportsMode && enabled && turnDataReady
  const mapQuery = useQuery(teamInformationMapQuerySpec(analyticScope, fetchEnabled))
  const gameId = analyticScope?.gameId ?? null
  const namesByLeagueTeamId = useLeagueTeamNames(gameId, supportsMode && enabled)

  const legendRows = useMemo(
    () =>
      teamInformationLegendRows(
        mapQuery.data?.teamInformationTeams ?? [],
        rosterUsernames(perspectives ?? [], turnUsernames),
        namesByLeagueTeamId
      ),
    [mapQuery.data?.teamInformationTeams, namesByLeagueTeamId, perspectives, turnUsernames]
  )

  const showLegend = supportsMode && enabled && legendRows.length > 0

  useEffect(() => {
    if (showLegend) return
    setHoveredLeagueTeamId(null)
  }, [setHoveredLeagueTeamId, showLegend])

  useEffect(() => () => setHoveredLeagueTeamId(null), [setHoveredLeagueTeamId])

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Team information options"
    >
      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={ownedPlanetsOnly}
          onChange={(event) => setOwnedPlanetsOnly(event.target.checked)}
          className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
        />
        <span className="min-w-0 truncate">Owned planets only</span>
      </label>
      {showLegend ? (
        <ul aria-label="League teams" className="flex flex-col gap-1">
          {legendRows.map((row) => {
            const legendText = teamInformationLegendText(row)
            return (
              <li
                key={row.leagueTeamId}
                className="flex min-w-0 items-start gap-2"
                title={teamInformationLegendHoverTitle(row.usernames)}
                onMouseEnter={() => setHoveredLeagueTeamId(row.leagueTeamId)}
                onMouseLeave={() => setHoveredLeagueTeamId(null)}
              >
                <input
                  type="checkbox"
                  checked={!hiddenLeagueTeamIds.includes(row.leagueTeamId)}
                  aria-label={`Show ${legendText} territory`}
                  onChange={(event) =>
                    setLeagueTeamRegionVisible(row.leagueTeamId, event.target.checked)
                  }
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
                />
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
                <span
                  className={cn(
                    'min-w-0 text-xs text-slate-300',
                    row.name == null && 'font-mono'
                  )}
                >
                  {legendText}
                </span>
              </li>
            )
          })}
        </ul>
      ) : null}
    </AnalyticSidebarTile>
  )
}
