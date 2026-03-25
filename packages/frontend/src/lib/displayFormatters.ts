import type { PlayerListLabelMode, SectorListLabelMode } from '../stores/displayPreferences'

export function formatViewpointRowLabel(
  mode: PlayerListLabelMode,
  playerName: string,
  raceName: string | null
): string {
  const race = raceName?.trim() ?? ''
  switch (mode) {
    case 'player_names_only':
      return playerName
    case 'race_names_only':
      return race || '—'
    case 'player_and_race_names':
      return race ? `${race} (${playerName})` : playerName
    default: {
      const _exhaustive: never = mode
      return _exhaustive
    }
  }
}

export function formatStoredGameRowLabel(
  mode: SectorListLabelMode,
  gameId: string,
  sectorName: string | null | undefined
): string {
  const name = sectorName?.trim() || null
  switch (mode) {
    case 'sector_ids_only':
      return gameId
    case 'sector_names_only':
      return name ?? gameId
    case 'both_ids_and_names':
      return name ? `${name} (${gameId})` : gameId
    default: {
      const _exhaustive: never = mode
      return _exhaustive
    }
  }
}
