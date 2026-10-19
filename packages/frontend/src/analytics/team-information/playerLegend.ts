import type { TeamInformationPlayer } from './wireSchema'
import { playerTerritoryFillColor } from './playerTerritoryColor'
import type { PlayerColorPaintSnapshot } from '../../lib/playerColor'

export type PlayerTerritoryLegendRow = {
  playerId: number
  fillColor: string
  /** Roster username. Null when the name is missing. */
  name: string | null
}

/** Visible legend and hover text: username, or the numeric id when it is missing. */
export function playerTerritoryLegendLabel(
  playerId: number,
  usernamesByPlayerId: ReadonlyMap<number, string>
): string {
  const username = usernamesByPlayerId.get(playerId)?.trim()
  return username ? username : String(playerId)
}

/**
 * One row per player who owns at least one planet.
 * Swatch color is the per-player palette, applied here so a settings change
 * updates the legend without a refetch.
 */
export function playerTerritoryLegendRows(
  players: readonly TeamInformationPlayer[],
  usernamesByPlayerId: ReadonlyMap<number, string>,
  snapshot: PlayerColorPaintSnapshot
): PlayerTerritoryLegendRow[] {
  return players.map((player) => {
    const username = usernamesByPlayerId.get(player.playerId)?.trim()
    return {
      playerId: player.playerId,
      fillColor: playerTerritoryFillColor(player.playerId, snapshot),
      name: username ? username : null,
    }
  })
}
