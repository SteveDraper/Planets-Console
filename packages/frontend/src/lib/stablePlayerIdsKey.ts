export function stablePlayerIdsKey(playerIds: readonly number[]): string {
  return [...playerIds].sort((left, right) => left - right).join(',')
}

export function playerIdsFromStableKey(playerIdsKey: string): number[] {
  if (playerIdsKey.length === 0) {
    return []
  }
  return playerIdsKey.split(',').map((part) => Number(part))
}
