import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { cn } from '../../lib/utils'
import { usePlayerColorsStore } from '../../stores/playerColors'
import { useShellStore } from '../../stores/shell'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'
import {
  byTeamForGame,
  useTeamInformationPreferencesStore,
} from '../../stores/teamInformationPreferences'
import { AnalyticSidebarTile, analyticDetailCheckboxClassName } from '../AnalyticSidebarTile'
import {
  playerTerritoryLegendLabel,
  playerTerritoryLegendRows,
} from './playerLegend'
import { rosterUsernames } from './rosterUsernames'
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
  const byTeamByGameId = useTeamInformationPreferencesStore((s) => s.byTeamByGameId)
  const setByTeamForGame = useTeamInformationPreferencesStore((s) => s.setByTeamForGame)
  const setHoveredLeagueTeamId = useTeamInformationHighlightStore(
    (s) => s.setHoveredLeagueTeamId
  )
  const setHoveredPlayerId = useTeamInformationHighlightStore((s) => s.setHoveredPlayerId)
  const paintSnapshot = usePlayerColorsStore((s) => s.paintSnapshot)
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const turnUsernames = useTurnRosterUsernames(analyticScope)

  const fetchEnabled = supportsMode && enabled && turnDataReady
  const mapQuery = useQuery(teamInformationMapQuerySpec(analyticScope, fetchEnabled))
  const gameId = analyticScope?.gameId ?? null
  const byTeam = byTeamForGame(byTeamByGameId, gameId)
  const namesByLeagueTeamId = useLeagueTeamNames(gameId, supportsMode && enabled)
  const usernamesByPlayerId = useMemo(
    () => rosterUsernames(perspectives ?? [], turnUsernames),
    [perspectives, turnUsernames]
  )

  const teamRows = useMemo(
    () =>
      teamInformationLegendRows(
        mapQuery.data?.teamInformationTeams ?? [],
        usernamesByPlayerId,
        namesByLeagueTeamId
      ),
    [mapQuery.data?.teamInformationTeams, namesByLeagueTeamId, usernamesByPlayerId]
  )
  const playerRows = useMemo(
    () =>
      playerTerritoryLegendRows(
        mapQuery.data?.teamInformationPlayers ?? [],
        usernamesByPlayerId,
        paintSnapshot
      ),
    [mapQuery.data?.teamInformationPlayers, paintSnapshot, usernamesByPlayerId]
  )

  const showTeamLegend = supportsMode && enabled && byTeam && teamRows.length > 0
  const showPlayerLegend = supportsMode && enabled && !byTeam && playerRows.length > 0

  useEffect(() => {
    if (showTeamLegend) return
    setHoveredLeagueTeamId(null)
  }, [setHoveredLeagueTeamId, showTeamLegend])

  useEffect(() => {
    if (showPlayerLegend) return
    setHoveredPlayerId(null)
  }, [setHoveredPlayerId, showPlayerLegend])

  useEffect(
    () => () => {
      setHoveredLeagueTeamId(null)
      setHoveredPlayerId(null)
    },
    [setHoveredLeagueTeamId, setHoveredPlayerId]
  )

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Territory options"
    >
      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={byTeam}
          onChange={(event) => {
            if (gameId == null) return
            setByTeamForGame(gameId, event.target.checked)
          }}
          className={analyticDetailCheckboxClassName}
        />
        <span className="min-w-0 truncate">By team</span>
      </label>
      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={ownedPlanetsOnly}
          onChange={(event) => setOwnedPlanetsOnly(event.target.checked)}
          className={analyticDetailCheckboxClassName}
        />
        <span className="min-w-0 truncate">Owned planets only</span>
      </label>
      {showTeamLegend ? (
        <ul aria-label="League teams" className="flex flex-col gap-1">
          {teamRows.map((row) => {
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
                  className={cn(analyticDetailCheckboxClassName, 'mt-0.5')}
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
      {showPlayerLegend ? (
        <ul aria-label="Players" className="flex flex-col gap-1">
          {playerRows.map((row) => {
            const legendText = playerTerritoryLegendLabel(row.playerId, usernamesByPlayerId)
            return (
              <li
                key={row.playerId}
                className="flex min-w-0 items-center gap-2"
                onMouseEnter={() => setHoveredPlayerId(row.playerId)}
                onMouseLeave={() => setHoveredPlayerId(null)}
              >
                <span
                  aria-hidden
                  data-fill-pattern="solid"
                  className="h-3 w-3 shrink-0 rounded-sm border border-black/30"
                  style={{ backgroundColor: row.fillColor }}
                />
                <span
                  className={cn(
                    'min-w-0 truncate text-xs text-slate-300',
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
