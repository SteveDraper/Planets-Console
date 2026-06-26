import { useMemo } from 'react'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetTableWire } from './fleetTableWireSchema'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

type FleetTableViewProps = {
  data: FleetTableWire
}

export function FleetTableView({ data }: FleetTableViewProps) {
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })

  const playersById = useMemo(
    () => new Map(data.players.map((player) => [player.playerId, player])),
    [data.players]
  )

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
            componentCatalog={data.componentCatalog}
          />
        )
      })}
    </div>
  )
}
