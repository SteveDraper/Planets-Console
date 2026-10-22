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

/** Open the document at a blob URL and keep that URL until the window closes. */
export function openTerritoryMovieWindow(html: string): void {
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  const opened = window.open(url, '_blank')
  if (opened == null) {
    URL.revokeObjectURL(url)
    throw new Error('The browser blocked the Territory movie window.')
  }
  const watch = window.setInterval(() => {
    if (opened.closed) {
      window.clearInterval(watch)
      URL.revokeObjectURL(url)
    }
  }, 1000)
}
