/**
 * Shared player identity colors for map/table paint.
 * Settings wires overrides into the storage port without changing callers.
 */

export const PLAYER_COLOR_PRESET = [
  '#38bdf8',
  '#f472b6',
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#fb7185',
  '#22d3ee',
  '#a3e635',
  '#f97316',
  '#818cf8',
  '#2dd4bf',
  '#e879f9',
  '#60a5fa',
  '#f43f5e',
  '#c084fc',
  '#84cc16',
] as const

export type PlayerColorOverrides = Readonly<Record<string, string>>

/** Storage port for per-player color overrides. */
export type PlayerColorOverrideStore = {
  getOverride: (playerId: number) => string | undefined
}

const emptyOverrideStore: PlayerColorOverrideStore = {
  getOverride: () => undefined,
}

let activeOverrideStore: PlayerColorOverrideStore = emptyOverrideStore

/** Install the override store consulted by {@link colorForPlayerId}. */
export function setPlayerColorOverrideStore(store: PlayerColorOverrideStore): void {
  activeOverrideStore = store
}

/** Restore the empty override store (tests / teardown). */
export function resetPlayerColorOverrideStore(): void {
  activeOverrideStore = emptyOverrideStore
}

export function playerColorOverrideStorageKey(playerId: number): string {
  return String(playerId)
}

export function defaultColorForPlayerId(playerId: number): string {
  const length = PLAYER_COLOR_PRESET.length
  const index = ((playerId % length) + length) % length
  return PLAYER_COLOR_PRESET[index]!
}

/** Non-empty override wins; otherwise the preset default. */
export function colorFromOverrideOrDefault(
  playerId: number,
  override: string | undefined
): string {
  if (override != null && override.length > 0) {
    return override
  }
  return defaultColorForPlayerId(playerId)
}

/**
 * Resolve a player's paint color from the override port, else the preset.
 * Non-React callers and render helpers use this entry point. React paint that
 * must update when Settings changes overrides should use `usePlayerColor`
 * from `stores/playerColors` (subscribes, then resolves through this function).
 */
export function colorForPlayerId(playerId: number): string {
  return colorFromOverrideOrDefault(playerId, activeOverrideStore.getOverride(playerId))
}
