import type { GameInfoResponse } from '../api/bff'
import { resolveRaceDisplayNameFromGameInfo } from './planetsNuRaceDisplayName'

/** 1-based player index in game info `players` order, with display name. */
export type PerspectiveRow = {
  ordinal: number
  name: string
  /** From turn-style `races` on the payload when present, else static HOST catalog. */
  raceName: string | null
}

/**
 * True when planets.nu reports the game as finished (status 3 / "Finished").
 * In-progress games only allow the logged-in player's perspective in the shell.
 */
export function isGameFinishedFromGameInfo(data: GameInfoResponse): boolean {
  const g = data.game
  if (!g || typeof g !== 'object') {
    return false
  }
  const rec = g as Record<string, unknown>
  const status = rec.status
  if (typeof status === 'number' && Number.isFinite(status) && status === 3) {
    return true
  }
  if (typeof status === 'string') {
    const parsed = Number.parseInt(status.trim(), 10)
    if (parsed === 3) {
      return true
    }
  }
  const statusname = rec.statusname
  if (typeof statusname === 'string' && statusname.trim().toLowerCase() === 'finished') {
    return true
  }
  return false
}

export function getLatestTurnFromGameInfo(data: GameInfoResponse): number | null {
  const g = data.game
  if (g && typeof g.turn === 'number' && Number.isFinite(g.turn)) {
    return g.turn
  }
  const s = data.settings
  if (s && typeof s.turn === 'number' && Number.isFinite(s.turn)) {
    return s.turn
  }
  return null
}

export function buildPerspectivesFromGameInfo(data: GameInfoResponse): PerspectiveRow[] {
  const raw = data.players
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.map((entry, i) => {
    let username = ''
    let raceId: number | null = null
    if (entry && typeof entry === 'object') {
      const o = entry as Record<string, unknown>
      const u = o.username
      if (typeof u === 'string') {
        username = u
      }
      const rid = o.raceid
      if (typeof rid === 'number' && Number.isFinite(rid)) {
        raceId = rid
      }
    }
    const trimmed = username.trim()
    const name = trimmed || `Player ${i + 1}`
    const raceName = resolveRaceDisplayNameFromGameInfo(raceId, data)
    return {
      ordinal: i + 1,
      name,
      raceName,
    }
  })
}

/** Sector title from game info (`game.name` or `settings.name`). */
export function getSectorDisplayNameFromGameInfo(data: GameInfoResponse): string | null {
  for (const key of ['game', 'settings'] as const) {
    const block = (data as Record<string, unknown>)[key]
    if (block != null && typeof block === 'object' && !Array.isArray(block)) {
      const n = (block as Record<string, unknown>).name
      if (typeof n === 'string') {
        const t = n.trim()
        if (t) return t
      }
    }
  }
  return null
}

/** 1-based perspective slot for Core/BFF, or null if unknown. */
export function perspectiveOrdinalForName(
  perspectives: PerspectiveRow[],
  name: string | null
): number | null {
  if (name == null || name.trim() === '') {
    return null
  }
  const hit = perspectives.find((p) => p.name === name)
  return hit?.ordinal ?? null
}

/** Match logged-in name to a player (case-insensitive); otherwise first perspective. */
export function viewpointNameForLogin(
  perspectives: PerspectiveRow[],
  loginName: string | null
): string | null {
  if (perspectives.length === 0) {
    return null
  }
  const n = loginName?.trim().toLowerCase() ?? ''
  if (n) {
    const hit = perspectives.find((p) => p.name.toLowerCase() === n)
    if (hit) {
      return hit.name
    }
  }
  return perspectives[0].name
}
