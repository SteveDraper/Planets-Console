import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
import type { HoveredTerritory } from './kinds'
import { useTerritoryLegendHover } from './useTerritoryLegendHover'
import {
  closeTerritoryMovieWindow,
  prepareTerritoryMovie,
  reserveTerritoryMovieWindow,
  showTerritoryMovieDocument,
} from './prepareTerritoryMovie'

function TerritoryLegendHoverTarget({
  territory,
  title,
  children,
}: {
  territory: HoveredTerritory
  title?: string
  children: ReactNode
}) {
  return (
    <span
      className="flex min-w-0 items-start gap-2"
      title={title}
      data-territory-hover=""
      data-territory-partition={territory.partition}
      data-territory-id={territory.id}
    >
      {children}
    </span>
  )
}

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
  const reservedMovieRef = useRef<{ window: Window; delivered: boolean } | null>(null)
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
  const legendRef = useTerritoryLegendHover(showTeamLegend || showPlayerLegend)

  useEffect(() => {
    movieMountedRef.current = true
    return () => {
      movieMountedRef.current = false
      const reserved = reservedMovieRef.current
      reservedMovieRef.current = null
      if (reserved != null && !reserved.delivered) closeTerritoryMovieWindow(reserved.window)
    }
  }, [])

  function discardReservedMovie(): void {
    const reserved = reservedMovieRef.current
    reservedMovieRef.current = null
    if (reserved != null) closeTerritoryMovieWindow(reserved.window)
  }

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
    let opened: Window
    try {
      opened = reserveTerritoryMovieWindow()
    } catch (err: unknown) {
      reportShellError(err instanceof Error ? err.message : 'Territory movie failed.')
      return
    }
    reservedMovieRef.current = { window: opened, delivered: false }
    movieBuildingRef.current = true
    setMovieBuilding(true)
    try {
      const html = await prepareTerritoryMovie({
        gameId: analyticScope.gameId,
        perspective: analyticScope.perspective,
        gameTurn,
        username: analyticScope.username ?? '',
      })
      const reserved = reservedMovieRef.current
      if (!movieMountedRef.current || reserved == null) {
        discardReservedMovie()
        return
      }
      reserved.delivered = true
      await showTerritoryMovieDocument(reserved.window, html)
      reservedMovieRef.current = null
    } catch (err: unknown) {
      discardReservedMovie()
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
        className="w-fit self-start cursor-pointer rounded-sm border-2 border-b-[#141618] border-l-[#6e747a] border-r-[#141618] border-t-[#c4c8cc] bg-[#3c4146] px-2.5 py-1 text-xs font-medium text-slate-100 shadow-[1px_1px_0_#0c0d0e] hover:bg-[#4a5056] active:translate-y-px active:border-b-[#c4c8cc] active:border-l-[#141618] active:border-r-[#6e747a] active:border-t-[#141618] active:shadow-none disabled:cursor-not-allowed disabled:opacity-50 disabled:active:translate-y-0"
        disabled={movieBuilding}
        onClick={() => {
          void openMovie()
        }}
      >
        Generate movie
      </button>
      {showTeamLegend ? (
        <ul ref={legendRef} aria-label="League teams" className="flex flex-col gap-1">
          {teamRows.map((row) => {
            const legendText = teamInformationLegendText(row)
            const territory = { partition: 'team' as const, id: row.leagueTeamId }
            return (
              <li key={row.leagueTeamId} className="flex min-w-0 items-start gap-2">
                <input
                  type="checkbox"
                  checked={!hiddenLeagueTeamIds.includes(row.leagueTeamId)}
                  aria-label={`Show ${legendText} territory`}
                  onChange={(event) =>
                    setLeagueTeamRegionVisible(row.leagueTeamId, event.target.checked)
                  }
                  className={cn(analyticDetailCheckboxClassName, 'mt-0.5')}
                />
                <TerritoryLegendHoverTarget
                  territory={territory}
                  title={teamInformationLegendHoverTitle(row.usernames)}
                >
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
                </TerritoryLegendHoverTarget>
              </li>
            )
          })}
        </ul>
      ) : null}
      {showPlayerLegend ? (
        <ul ref={legendRef} aria-label="Players" className="flex flex-col gap-1">
          {playerRows.map((row) => {
            const legendText = playerTerritoryLegendLabel(row.playerId, usernamesByPlayerId)
            const territory = { partition: 'player' as const, id: row.playerId }
            return (
              <li key={row.playerId} className="flex min-w-0 items-start gap-2">
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
                <TerritoryLegendHoverTarget territory={territory}>
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
                </TerritoryLegendHoverTarget>
              </li>
            )
          })}
        </ul>
      ) : null}
    </AnalyticSidebarTile>
  )
}
