/** Wire status on game-info ``players[]`` when eliminated (Planets.nu). */
export const ELIMINATED_PLAYER_WIRE_STATUS = 3

/** Build player-id → username map from a turn ensure / TurnInfo JSON payload. */
export function turnUsernamesByPlayerIdFromPayload(data: unknown): Map<number, string> {
  const map = new Map<number, string>()
  if (data == null || typeof data !== 'object') {
    return map
  }
  const record = data as Record<string, unknown>
  const addPlayer = (entry: unknown) => {
    if (entry == null || typeof entry !== 'object') {
      return
    }
    const player = entry as Record<string, unknown>
    const id = player.id
    const username = player.username
    if (typeof id !== 'number' || !Number.isFinite(id)) {
      return
    }
    if (typeof username !== 'string') {
      return
    }
    const trimmed = username.trim()
    map.set(id, trimmed || username)
  }
  const players = record.players
  if (Array.isArray(players)) {
    for (const entry of players) {
      addPlayer(entry)
    }
  }
  // Perspective player overwrites roster entries for the same id.
  addPlayer(record.player)
  return map
}
