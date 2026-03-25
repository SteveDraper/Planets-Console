import type { GameInfoResponse } from '../api/bff'
import raceCatalog from '../assets/planetsNuRaceNames.json'

const CATALOG_BY_ID: ReadonlyMap<number, string> = (() => {
  const m = new Map<number, string>()
  for (const row of raceCatalog.races) {
    if (typeof row.id === 'number' && Number.isFinite(row.id) && typeof row.name === 'string') {
      const t = row.name.trim()
      if (t) {
        m.set(row.id, t)
      }
    }
  }
  return m
})()

/**
 * Stable race display names for planets.nu (HOST `raceid`). The live API only ships the full
 * `races` table on turn RST; game `loadinfo` does not, so the UI uses this catalog as fallback.
 */
export function planetsNuRaceDisplayNameFromCatalog(raceId: number): string | null {
  if (!Number.isFinite(raceId)) {
    return null
  }
  return CATALOG_BY_ID.get(raceId) ?? null
}

function raceNameFromGameInfoWire(data: GameInfoResponse, raceId: number): string | null {
  const races = (data as Record<string, unknown>).races
  if (!Array.isArray(races)) {
    return null
  }
  for (const item of races) {
    if (item == null || typeof item !== 'object') continue
    const rec = item as Record<string, unknown>
    const id = rec.id
    const name = rec.name
    if (typeof id === 'number' && id === raceId && typeof name === 'string') {
      const t = name.trim()
      if (t) {
        return t
      }
    }
  }
  return null
}

/** Prefer turn-style `races` on the payload when present; otherwise the static HOST catalog. */
export function resolveRaceDisplayNameFromGameInfo(
  raceId: number | null,
  data: GameInfoResponse
): string | null {
  if (raceId == null || !Number.isFinite(raceId)) {
    return null
  }
  return raceNameFromGameInfoWire(data, raceId) ?? planetsNuRaceDisplayNameFromCatalog(raceId)
}
