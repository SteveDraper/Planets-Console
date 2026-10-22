import {
  discardTerritoryMoviePage,
  ensureTurnData,
  fetchTerritoryMovie,
  publishTerritoryMoviePage,
} from '../../api/bff'
import { buildTerritoryMovieDocument } from './territoryMovieDocument'
import { moviePalette } from './territoryMoviePalette'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'

async function assertReadableRings(encoded: string, turnCount: number): Promise<void> {
  const runtime = createTerritoryMovieRuntime()
  let bytes: Uint8Array
  try {
    bytes = await runtime.inflateBase64(encoded)
  } catch {
    throw new Error(runtime.unreadableMovieMessage)
  }
  if (runtime.decodeRings(bytes, turnCount) == null) {
    throw new Error(runtime.unreadableMovieMessage)
  }
}

export type PrepareTerritoryMovieInput = {
  gameId: string
  perspective: number
  /** `GameInfo.game.turn`. Not the shell's selected turn. */
  gameTurn: number
  username: string
}

/**
 * Ensure host turns 1 through `gameTurn` for this viewpoint, then build the movie file.
 * Turns after elimination are included. Load-all's shorter span is a different route.
 */
export async function prepareTerritoryMovie(input: PrepareTerritoryMovieInput): Promise<string> {
  if (!Number.isInteger(input.gameTurn) || input.gameTurn < 1) {
    throw new Error("Territory movie needs the game's current turn.")
  }
  const username = input.username.trim()
  for (let turn = 1; turn <= input.gameTurn; turn += 1) {
    await ensureTurnData(input.gameId, {
      turn,
      perspective: input.perspective,
      username,
    })
  }
  const payload = await fetchTerritoryMovie(input.gameId, input.perspective)
  await assertReadableRings(payload.rings, payload.turn)
  const ownerCount = Math.max(payload.players.length, payload.teams.length)
  const palette = await moviePalette(ownerCount)
  return buildTerritoryMovieDocument({ ...payload, palette })
}

/**
 * Open a blank window during the click.
 * A later `window.open` is outside the click and the browser blocks it.
 */
export function reserveTerritoryMovieWindow(): Window {
  const opened = window.open('about:blank', '_blank')
  if (opened == null) {
    throw new Error('The browser blocked the Territory movie window.')
  }
  const body = opened.document.body
  if (body != null) {
    opened.document.title = 'Territory movie'
    body.textContent = 'Building the Territory movie…'
  }
  return opened
}

/** Navigate the blank window to the console address for this document. */
export async function showTerritoryMovieDocument(opened: Window, html: string): Promise<void> {
  const page = await publishTerritoryMoviePage(html)
  if (opened.closed) {
    await discardTerritoryMoviePage(page.id)
    return
  }
  opened.location.href = new URL(page.path, window.location.origin).href
  const watch = window.setInterval(() => {
    if (opened.closed) {
      window.clearInterval(watch)
      void discardTerritoryMoviePage(page.id)
    }
  }, 1000)
}

export function closeTerritoryMovieWindow(opened: Window): void {
  if (!opened.closed) opened.close()
}
