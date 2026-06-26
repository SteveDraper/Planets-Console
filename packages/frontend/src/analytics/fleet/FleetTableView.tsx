import { useMemo } from 'react'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import {
  orderFleetSidebarPlayers,
  resolveFleetPlayerVisible,
} from './fleetPlayerVisibilityPolicy'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetTableWire } from './fleetTableWireSchema'

type FleetTableViewProps = {
  data: FleetTableWire
  players: readonly PerspectiveRow[]
  viewpointPlayerId: number | null
}

export function FleetTableView({
  data,
  players,
  viewpointPlayerId,
}: FleetTableViewProps) {
  const visibilityOverrides = useFleetPlayerVisibilityStore((state) => state.overrides)
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
