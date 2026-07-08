import {
  buildGameInfoShellContext,
  getLatestTurnFromGameInfo,
  selectableTurnMaxForShell,
} from '../lib/gameInfoShell'
import { loadGameFromStorage, type StorageGameLoadResult } from '../lib/loadGameFromStorage'
import { fetchStoredGameInfo, type GameInfoResponse } from '../api/bff'
import type { ApplyGameInfoRefreshOptions } from '../stores/shell'
import { useShellStore } from '../stores/shell'

export type ShellGameBootstrapResult =
  | { kind: 'stored-info'; data: GameInfoResponse }
  | { kind: 'storage-only'; data: StorageGameLoadResult }

export async function fetchShellGameBootstrap(
  gameId: string,
  loginName: string
): Promise<ShellGameBootstrapResult> {
  if (loginName.trim()) {
    return {
      kind: 'stored-info',
      data: await fetchStoredGameInfo(gameId),
    }
  }
  return {
    kind: 'storage-only',
    data: await loadGameFromStorage(gameId),
  }
}

export type ApplyShellGameBootstrapOptions = {
  /** When true, storage-only bootstrap sets viewpoint from stored turn data instead of keeping shell override. */
  storageOnlyUseDefaultViewpoint?: boolean
}

export function applyShellGameBootstrapResult(
  gameId: string,
  result: ShellGameBootstrapResult,
  options?: ApplyShellGameBootstrapOptions
): void {
  const applyGameInfoRefresh = useShellStore.getState().applyGameInfoRefresh
  if (result.kind === 'storage-only') {
    const loaded = result.data
    const refreshOptions: ApplyGameInfoRefreshOptions = {
      storageOnlyLoad: true,
      storageAvailablePerspectives: loaded.storedPerspectives,
    }
    if (options?.storageOnlyUseDefaultViewpoint) {
      refreshOptions.perspectiveOverrideOrdinal = loaded.defaultViewpointOrdinal
    }
    applyGameInfoRefresh(gameId, buildGameInfoShellContext(loaded.gameInfo), refreshOptions)
    return
  }
  const latestTurn = getLatestTurnFromGameInfo(result.data)
  applyGameInfoRefresh(gameId, buildGameInfoShellContext(result.data), {
    selectableTurnMax: selectableTurnMaxForShell(latestTurn),
  })
}
