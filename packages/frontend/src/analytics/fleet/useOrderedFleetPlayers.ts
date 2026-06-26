import { useCallback, useMemo } from 'react'
import { playerIdForViewpointName } from '../../lib/gameInfoShell'
import { deriveSelectedViewpointName } from '../../shell/shellContext'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import {
  orderFleetSidebarPlayers,
  resolveFleetPlayerVisible,
} from './fleetPlayerVisibilityPolicy'

type UseOrderedFleetPlayersOptions = {
  /** When true, only players with fleet visibility enabled are returned. */
  visibleOnly?: boolean
}

export function useOrderedFleetPlayers(options: UseOrderedFleetPlayersOptions = {}) {
  const { visibleOnly = false } = options
  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideName = useShellStore((s) => s.perspectiveOverrideName)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const loginName = useSessionStore((s) => s.name)
  const visibilityOverrides = useFleetPlayerVisibilityStore((state) => state.overrides)

  const shellPlayers = gameInfoContext?.perspectives ?? []
  const viewpointPlayerId = useMemo(() => {
    const selectedViewpointName = deriveSelectedViewpointName({
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideName,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
    })
    return playerIdForViewpointName(shellPlayers, selectedViewpointName)
  }, [
    selectedGameId,
    gameInfoContext,
    selectedTurn,
    perspectiveOverrideName,
    loginName,
    storageOnlyLoad,
    storageAvailablePerspectives,
    shellPlayers,
  ])

  const orderedPlayers = useMemo(
    () => orderFleetSidebarPlayers(shellPlayers, viewpointPlayerId),
    [shellPlayers, viewpointPlayerId]
  )

  const players = useMemo(() => {
    if (!visibleOnly) {
      return orderedPlayers
    }
    return orderedPlayers.filter((player) =>
      resolveFleetPlayerVisible(player.playerId, viewpointPlayerId, visibilityOverrides)
    )
  }, [orderedPlayers, visibleOnly, viewpointPlayerId, visibilityOverrides])

  const isPlayerVisible = useCallback(
    (playerId: number) =>
      resolveFleetPlayerVisible(playerId, viewpointPlayerId, visibilityOverrides),
    [viewpointPlayerId, visibilityOverrides]
  )

  return {
    players,
    viewpointPlayerId,
    isPlayerVisible,
  }
}
