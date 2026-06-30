import { useMemo } from 'react'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { mergeFleetPlayerWithStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableWire } from './fleetTableWireSchema'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

type FleetTableViewProps = {
  data: FleetTableWire
  streamPlayersById?: Map<number, FleetPlayerStreamSlice>
}

export function FleetTableView({ data, streamPlayersById }: FleetTableViewProps) {
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
        const streamSlice = streamPlayersById?.get(player.playerId)
        const merged = mergeFleetPlayerWithStreamSlice(
          wirePlayer,
          streamSlice,
          player.name
        )
        return (
          <FleetPlayerTableTile
            key={player.playerId}
            playerName={merged.playerName}
            records={merged.records}
            discrepancy={merged.discrepancy}
            componentCatalog={data.componentCatalog}
            streamError={merged.streamError}
          />
        )
      })}
    </div>
  )
}
