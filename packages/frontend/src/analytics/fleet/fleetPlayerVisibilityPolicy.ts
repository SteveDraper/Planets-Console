import type { PerspectiveRow } from '../../lib/gameInfoShell'

/** Persisted per-player fleet visibility overrides (playerId string keys). */
export type FleetPlayerVisibilityOverrides = Record<string, boolean>

export function fleetPlayerVisibilityStorageKey(playerId: number): string {
  return String(playerId)
}

/** Default visibility: all players on until the user toggles an override. */
export function defaultFleetPlayerVisible(
  _playerId: number,
  _viewpointPlayerId: number | null
): boolean {
  return true
}

export function resolveFleetPlayerVisible(
  playerId: number,
  viewpointPlayerId: number | null,
  overrides: FleetPlayerVisibilityOverrides
): boolean {
  const key = fleetPlayerVisibilityStorageKey(playerId)
  if (Object.prototype.hasOwnProperty.call(overrides, key)) {
    return overrides[key]
  }
  return defaultFleetPlayerVisible(playerId, viewpointPlayerId)
}

/** Viewpoint player first, then remaining players in game-info order. */
export function orderFleetSidebarPlayers(
  players: readonly PerspectiveRow[],
  viewpointPlayerId: number | null
): PerspectiveRow[] {
  if (viewpointPlayerId == null) {
    return [...players]
  }
  const viewpoint = players.find((player) => player.playerId === viewpointPlayerId)
  if (!viewpoint) {
    return [...players]
  }
  return [viewpoint, ...players.filter((player) => player.playerId !== viewpointPlayerId)]
}

export function viewpointPlayerIdForName(
  players: readonly PerspectiveRow[],
  viewpointName: string | null
): number | null {
  if (viewpointName == null || viewpointName.trim() === '') {
    return null
  }
  const hit = players.find((player) => player.name === viewpointName)
  return hit?.playerId ?? null
}

export function visibleFleetPlayerIds(
  players: readonly PerspectiveRow[],
  viewpointPlayerId: number | null,
  overrides: FleetPlayerVisibilityOverrides
): number[] {
  return players
    .filter((player) =>
      resolveFleetPlayerVisible(player.playerId, viewpointPlayerId, overrides)
    )
    .map((player) => player.playerId)
}
