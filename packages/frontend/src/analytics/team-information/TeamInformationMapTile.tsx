import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { cn } from '../../lib/utils'
import { usePlayerColorsStore } from '../../stores/playerColors'
import { useShellStore } from '../../stores/shell'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'
import {
  byTeamForGame,
  hiddenPlayerIdsForGame,
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
import { openTerritoryMovieWindow, prepareTerritoryMovie } from './prepareTerritoryMovie'

type TeamInformationMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  analyticScope: AnalyticShellScope | null
  turnDataReady: boolean
  reportShellError: (message: string) => void
}

export function TeamInformationMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  analyticScope,
  turnDataReady,
  reportShellError,
}: TeamInformationMapTileProps) {
  const ownedPlanetsOnly = useTeamInformationPreferencesStore((s) => s.ownedPlanetsOnly)
  const setOwnedPlanetsOnly = useTeamInformationPreferencesStore((s) => s.setOwnedPlanetsOnly)
  const hiddenLeagueTeamIds = useTeamInformationPreferencesStore((s) => s.hiddenLeagueTeamIds)
  const setLeagueTeamRegionVisible = useTeamInformationPreferencesStore(
    (s) => s.setLeagueTeamRegionVisible
  )
  const hiddenPlayerIdsByGameId = useTeamInformationPreferencesStore(
    (s) => s.hiddenPlayerIdsByGameId
  )
  const setPlayerTerritoryVisible = useTeamInformationPreferencesStore(
    (s) => s.setPlayerTerritoryVisible
  )
  const byTeamByGameId = useTeamInformationPreferencesStore((s) => s.byTeamByGameId)
  const setByTeamForGame = useTeamInformationPreferencesStore((s) => s.setByTeamForGame)
  const setHoveredTerritory = useTeamInformationHighlightStore((s) => s.setHoveredTerritory)
  const paintSnapshot = usePlayerColorsStore((s) => s.paintSnapshot)
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const turnUsernames = useTurnRosterUsernames(analyticScope)

  const fetchEnabled = supportsMode && enabled && turnDataReady
  const mapQuery = useQuery(teamInformationMapQuerySpec(analyticScope, fetchEnabled))
  const gameId = analyticScope?.gameId ?? null
  const gameTurn = useShellStore((s) => s.gameInfoContext?.turn ?? null)
  const [movieBuilding, setMovieBuilding] = useState(false)
  const movieBuildingRef = useRef(false)
  const movieMountedRef = useRef(true)
  const byTeam = byTeamForGame(byTeamByGameId, gameId)
  const hiddenPlayerIds = hiddenPlayerIdsForGame(hiddenPlayerIdsByGameId, gameId)
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
    movieMountedRef.current = true
    return () => {
      movieMountedRef.current = false
    }
  }, [])

  async function openMovie(): Promise<void> {
    if (movieBuildingRef.current) return
    if (analyticScope == null) {
      reportShellError('Choose a game and viewpoint before opening the Territory movie.')
      return
    }
    if (gameTurn == null) {
      reportShellError("Territory movie needs the game's current turn.")
      return
    }
    movieBuildingRef.current = true
    setMovieBuilding(true)
    try {
      const html = await prepareTerritoryMovie({
        gameId: analyticScope.gameId,
        perspective: analyticScope.perspective,
        gameTurn,
        username: analyticScope.username ?? '',
      })
      if (!movieMountedRef.current) return
      openTerritoryMovieWindow(html)
    } catch (err: unknown) {
      if (!movieMountedRef.current) return
      reportShellError(err instanceof Error ? err.message : 'Territory movie failed.')
    } finally {
      movieBuildingRef.current = false
      if (movieMountedRef.current) setMovieBuilding(false)
    }
  }

  useEffect(() => {
    const hovered = useTeamInformationHighlightStore.getState().hoveredTerritory
    if (hovered != null) {
      const legendShown = hovered.partition === 'team' ? showTeamLegend : showPlayerLegend
      if (!legendShown) setHoveredTerritory(null)
    }
    return () => setHoveredTerritory(null)
  }, [setHoveredTerritory, showPlayerLegend, showTeamLegend])

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
      <button
        type="button"
        className="rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1 text-left text-xs text-slate-200 hover:bg-[#4a4f54] disabled:cursor-not-allowed disabled:opacity-50"
        disabled={movieBuilding}
        onClick={() => {
          void openMovie()
        }}
      >
        Territory movie
      </button>
      {showTeamLegend ? (
        <ul aria-label="League teams" className="flex flex-col gap-1">
          {teamRows.map((row) => {
            const legendText = teamInformationLegendText(row)
            return (
              <li
                key={row.leagueTeamId}
                className="flex min-w-0 items-start gap-2"
                title={teamInformationLegendHoverTitle(row.usernames)}
                onMouseEnter={() =>
                  setHoveredTerritory({ partition: 'team', id: row.leagueTeamId })
                }
                onMouseLeave={() => setHoveredTerritory(null)}
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
                className="flex min-w-0 items-start gap-2"
                onMouseEnter={() =>
                  setHoveredTerritory({ partition: 'player', id: row.playerId })
                }
                onMouseLeave={() => setHoveredTerritory(null)}
              >
                <input
                  type="checkbox"
                  checked={!hiddenPlayerIds.includes(row.playerId)}
                  aria-label={`Show ${legendText} territory`}
                  onChange={(event) => {
                    if (gameId == null || gameId.length === 0) return
                    setPlayerTerritoryVisible(gameId, row.playerId, event.target.checked)
                  }}
                  className={cn(analyticDetailCheckboxClassName, 'mt-0.5')}
                />
                <span
                  aria-hidden
                  data-fill-pattern="solid"
                  className="mt-0.5 h-3 w-3 shrink-0 rounded-sm border border-black/30"
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
