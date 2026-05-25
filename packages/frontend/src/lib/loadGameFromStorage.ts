import type { GameInfoResponse } from '../api/bff'
import { fetchStoredGameInfo, fetchStoredTurnPerspectives, isBffNotFoundError } from '../api/bff'
import {
  LOGIN_REQUIRED_FOR_GAME_SELECTION,
  getLatestTurnFromGameInfo,
  SPECTATOR_VIEWPOINT_NAME,
  viewpointNameForStoredPerspective,
  buildPerspectivesFromGameInfo,
} from './gameInfoShell'

export type StorageGameLoadResult = {
  gameInfo: GameInfoResponse
  turn: number
  storedPerspectives: number[]
  defaultViewpointName: string
}

/** Load game info and turn availability from storage only; no Planets.nu refresh. */
export async function loadGameFromStorage(gameId: string): Promise<StorageGameLoadResult> {
  let gameInfo: GameInfoResponse
  try {
    gameInfo = await fetchStoredGameInfo(gameId)
  } catch (err) {
    if (isBffNotFoundError(err)) {
      throw new Error(LOGIN_REQUIRED_FOR_GAME_SELECTION)
    }
    throw err
  }

  const turn = getLatestTurnFromGameInfo(gameInfo)
  if (turn == null || !Number.isFinite(turn) || turn < 1) {
    throw new Error(LOGIN_REQUIRED_FOR_GAME_SELECTION)
  }

  const { perspectives: storedPerspectives } = await fetchStoredTurnPerspectives(
    gameId,
    Math.floor(turn)
  )
  if (storedPerspectives.length === 0) {
    throw new Error(LOGIN_REQUIRED_FOR_GAME_SELECTION)
  }

  const playerPerspectives = buildPerspectivesFromGameInfo(gameInfo)
  const defaultViewpointName = viewpointNameForStoredPerspective(
    storedPerspectives[0],
    playerPerspectives
  )
  if (defaultViewpointName == null) {
    throw new Error(LOGIN_REQUIRED_FOR_GAME_SELECTION)
  }

  return {
    gameInfo,
    turn: Math.floor(turn),
    storedPerspectives,
    defaultViewpointName,
  }
}
