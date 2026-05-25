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

/** 1-based perspective slot for Core/BFF; 0 for spectator pseudo-view. */
export function perspectiveOrdinalForName(
  perspectives: PerspectiveRow[],
  name: string | null
): number | null {
  if (name == null || name.trim() === '') {
    return null
  }
  if (isSpectatorViewpointName(name)) {
    return PSEUDO_VIEWPOINT_PERSPECTIVE
  }
  const hit = perspectives.find((p) => p.name === name)
  return hit?.ordinal ?? null
}

/** Perspective slot used when login is not a game player on an in-progress game. */
export const PSEUDO_VIEWPOINT_PERSPECTIVE = 0

/** Shell viewpoint label for pseudo-viewpoint 0 (host/spectator). */
export const SPECTATOR_VIEWPOINT_NAME = '<Spectator>'

export function isSpectatorViewpointName(name: string | null): boolean {
  return name === SPECTATOR_VIEWPOINT_NAME
}

/** True when login name matches a player in the game (case-insensitive). */
export function isLoginAmongGamePlayers(
  perspectives: PerspectiveRow[],
  loginName: string | null
): boolean {
  const n = loginName?.trim().toLowerCase() ?? ''
  if (!n) {
    return false
  }
  return perspectives.some((p) => p.name.toLowerCase() === n)
}

/** Use pseudo-viewpoint 0 for turn load when login is set but not among game players. */
export function shouldUsePseudoViewpointForLogin(
  perspectives: PerspectiveRow[],
  loginName: string | null,
  isGameFinished: boolean
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  if (isGameFinished || loginTrimmed === '' || perspectives.length === 0) {
    return false
  }
  return !isLoginAmongGamePlayers(perspectives, loginName)
}

/**
 * Highest turn selectable in the shell. For host pseudo-view (perspective 0) on in-progress
 * games, Planets.nu loadturn accepts playerid=0 only for turns before the current one.
 */
export function selectableTurnMaxForShell(
  latestTurn: number | null,
  perspectives: PerspectiveRow[],
  loginName: string | null,
  isGameFinished: boolean
): number | null {
  if (latestTurn == null || !Number.isFinite(latestTurn) || latestTurn < 1) {
    return null
  }
  const max = Math.floor(latestTurn)
  if (shouldUsePseudoViewpointForLogin(perspectives, loginName, isGameFinished) && max > 1) {
    return max - 1
  }
  return max
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

/** Player display name for a 1-based perspective slot, or null if unknown. */
export function perspectiveNameForOrdinal(
  perspectives: PerspectiveRow[],
  ordinal: number
): string | null {
  const hit = perspectives.find((p) => p.ordinal === ordinal)
  return hit?.name ?? null
}

/** Shown when a game or turn must be fetched from Planets.nu but login is missing. */
export const LOGIN_REQUIRED_FOR_GAME_SELECTION =
  'Set login name in the header before selecting a game.'
