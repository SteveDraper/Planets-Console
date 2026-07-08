import type { GameInfoResponse } from '../api/bff'
import type { GameInfoShellContext } from '../stores/shell'
import { resolveRaceDisplayNameFromGameInfo } from './planetsNuRaceDisplayName'
import { stellarCartographySettingsGatesFromGameInfo } from './stellarCartographySettings'

import { ELIMINATED_PLAYER_WIRE_STATUS } from './turnPlayerUsernames'

/** 1-based player index in game info `players` order, with display name. */
export type PerspectiveRow = {
  ordinal: number
  /** Host player id from game info `players[].id` when present, else ordinal. */
  playerId: number
  /** Username from stored game info (may be ``dead`` for eliminated slots). */
  name: string
  /** From turn-style `races` on the payload when present, else static HOST catalog. */
  raceName: string | null
  /** Turn the player was eliminated, or null when still active at game-info snapshot. */
  eliminationTurn: number | null
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
    let playerId = i + 1
    let eliminationTurn: number | null = null
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
      const hostPlayerId = o.id
      if (typeof hostPlayerId === 'number' && Number.isFinite(hostPlayerId)) {
        playerId = hostPlayerId
      }
      const status = o.status
      const statusTurn = o.statusturn
      if (
        status === ELIMINATED_PLAYER_WIRE_STATUS &&
        typeof statusTurn === 'number' &&
        Number.isFinite(statusTurn)
      ) {
        eliminationTurn = Math.floor(statusTurn)
      }
    }
    const trimmed = username.trim()
    const name = trimmed || `Player ${i + 1}`
    const raceName = resolveRaceDisplayNameFromGameInfo(raceId, data)
    return {
      ordinal: i + 1,
      playerId,
      name,
      raceName,
      eliminationTurn,
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

/** Host player id for a shell viewpoint name, or null when unknown or empty. */
export function playerIdForViewpointName(
  perspectives: PerspectiveRow[],
  name: string | null
): number | null {
  if (name == null || name.trim() === '') {
    return null
  }
  const hit = perspectives.find((p) => p.name === name)
  return hit?.playerId ?? null
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
 * Highest turn selectable in the shell (latest turn from game info when known).
 */
export function selectableTurnMaxForShell(latestTurn: number | null): number | null {
  if (latestTurn == null || !Number.isFinite(latestTurn) || latestTurn < 1) {
    return null
  }
  return Math.floor(latestTurn)
}

/** Shell viewpoint label for a perspective row at the viewed data turn. */
export function perspectiveDisplayName(
  row: PerspectiveRow,
  viewedDataTurn: number | null,
  turnUsernamesByPlayerId: ReadonlyMap<number, string> | null
): string {
  const turnUsername = turnUsernamesByPlayerId?.get(row.playerId)?.trim()
  if (
    viewedDataTurn != null &&
    turnUsername &&
    (row.eliminationTurn == null || viewedDataTurn < row.eliminationTurn)
  ) {
    return turnUsername
  }
  return row.name
}

/** Match logged-in name to a 1-based perspective slot; otherwise first slot. */
export function viewpointOrdinalForLogin(
  perspectives: PerspectiveRow[],
  loginName: string | null
): number | null {
  if (perspectives.length === 0) {
    return null
  }
  const n = loginName?.trim().toLowerCase() ?? ''
  if (n) {
    const hit = perspectives.find((p) => p.name.toLowerCase() === n)
    if (hit) {
      return hit.ordinal
    }
  }
  return perspectives[0]?.ordinal ?? null
}

/** Host player id for a 1-based perspective slot, or null when unknown or spectator. */
export function playerIdForPerspectiveOrdinal(
  perspectives: PerspectiveRow[],
  ordinal: number | null
): number | null {
  if (ordinal == null || ordinal === PSEUDO_VIEWPOINT_PERSPECTIVE) {
    return null
  }
  const hit = perspectives.find((p) => p.ordinal === ordinal)
  return hit?.playerId ?? null
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

/** Viewpoint label for a stored perspective slot (including pseudo-viewpoint 0). */
export function viewpointNameForStoredPerspective(
  ordinal: number,
  perspectives: PerspectiveRow[]
): string | null {
  if (ordinal === PSEUDO_VIEWPOINT_PERSPECTIVE) {
    return SPECTATOR_VIEWPOINT_NAME
  }
  return perspectiveNameForOrdinal(perspectives, ordinal)
}

/** Shown when a game or turn must be fetched from Planets.nu but login is missing. */
export const LOGIN_REQUIRED_FOR_GAME_SELECTION =
  'Set login name in the header before selecting a game.'

/** Build shell snapshot fields from a game-info payload. */
export function buildGameInfoShellContext(data: GameInfoResponse): GameInfoShellContext {
  return {
    turn: getLatestTurnFromGameInfo(data),
    perspectives: buildPerspectivesFromGameInfo(data),
    isGameFinished: isGameFinishedFromGameInfo(data),
    sectorDisplayName: getSectorDisplayNameFromGameInfo(data),
    stellarCartographyGates: stellarCartographySettingsGatesFromGameInfo(data),
  }
}
