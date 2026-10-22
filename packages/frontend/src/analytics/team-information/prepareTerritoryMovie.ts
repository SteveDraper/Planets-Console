import { ensureTurnData, fetchTerritoryMovie } from '../../api/bff'
import { buildTerritoryMovieDocument } from './territoryMovieDocument'
import { moviePalette } from './territoryMoviePalette'

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

/** Replace the blank window with the movie blob and keep that URL until the window closes. */
export function showTerritoryMovieDocument(opened: Window, html: string): void {
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  opened.location.href = url
  const watch = window.setInterval(() => {
    if (opened.closed) {
      window.clearInterval(watch)
      URL.revokeObjectURL(url)
    }
  }, 1000)
}

export function closeTerritoryMovieWindow(opened: Window): void {
  if (!opened.closed) opened.close()
}
