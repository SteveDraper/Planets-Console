import { useCallback, useMemo } from 'react'
import { playerIdForPerspectiveOrdinal } from '../../lib/gameInfoShell'
import { deriveSelectedViewpointOrdinal } from '../../shell/shellContext'
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
  const perspectiveOverrideOrdinal = useShellStore((s) => s.perspectiveOverrideOrdinal)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const loginName = useSessionStore((s) => s.name)
  const visibilityOverrides = useFleetPlayerVisibilityStore((state) => state.overrides)

  const shellPlayers = gameInfoContext?.perspectives ?? []
  const viewpointPlayerId = useMemo(() => {
    const selectedOrdinal = deriveSelectedViewpointOrdinal({
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideOrdinal,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
      viewedDataTurn: selectedTurn,
      turnUsernamesByPlayerId: null,
    })
    return playerIdForPerspectiveOrdinal(shellPlayers, selectedOrdinal)
  }, [
    selectedGameId,
    gameInfoContext,
    selectedTurn,
    perspectiveOverrideOrdinal,
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
