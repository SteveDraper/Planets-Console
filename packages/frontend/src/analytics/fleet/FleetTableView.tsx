import { useMemo } from 'react'
import { playerIdForViewpointName } from '../../lib/gameInfoShell'
import { deriveSelectedViewpointName } from '../../shell/shellContext'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import {
  orderFleetSidebarPlayers,
  resolveFleetPlayerVisible,
} from './fleetPlayerVisibilityPolicy'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetTableWire } from './fleetTableWireSchema'

type FleetTableViewProps = {
  data: FleetTableWire
}

export function FleetTableView({ data }: FleetTableViewProps) {
  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideName = useShellStore((s) => s.perspectiveOverrideName)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const loginName = useSessionStore((s) => s.name)
  const visibilityOverrides = useFleetPlayerVisibilityStore((state) => state.overrides)

  const players = gameInfoContext?.perspectives ?? []
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
    return playerIdForViewpointName(players, selectedViewpointName)
  }, [
    selectedGameId,
    gameInfoContext,
    selectedTurn,
    perspectiveOverrideName,
    loginName,
    storageOnlyLoad,
    storageAvailablePerspectives,
    players,
  ])

  const playersById = useMemo(
    () => new Map(data.players.map((player) => [player.playerId, player])),
    [data.players]
  )

  const visiblePlayers = useMemo(() => {
    const enabled = players.filter((player) =>
      resolveFleetPlayerVisible(player.playerId, viewpointPlayerId, visibilityOverrides)
    )
    return orderFleetSidebarPlayers(enabled, viewpointPlayerId)
  }, [players, viewpointPlayerId, visibilityOverrides])

  if (visiblePlayers.length === 0) {
    return (
      <p className="p-4 text-sm text-slate-400">
        Enable at least one player in the Fleet sidebar to see fleet tables.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {visiblePlayers.map((player) => {
        const wirePlayer = playersById.get(player.playerId)
        return (
          <FleetPlayerTableTile
            key={player.playerId}
            playerName={wirePlayer?.playerName ?? player.name}
            records={wirePlayer?.records ?? []}
            discrepancy={wirePlayer?.discrepancy}
          />
        )
      })}
    </div>
  )
}
