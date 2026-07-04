import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetComponentCatalog } from './fleetComponentCatalog'
import { EMPTY_FLEET_COMPONENT_CATALOG } from './fleetComponentCatalog'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { mergeFleetPlayerWithStreamSlice } from './fleetTablePlayerStreamState'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

type FleetTableViewProps = {
  componentCatalog?: FleetComponentCatalog
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
}

export function FleetTableView({
  componentCatalog = EMPTY_FLEET_COMPONENT_CATALOG,
  streamPlayersById,
}: FleetTableViewProps) {
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })

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
        const streamSlice = streamPlayersById.get(player.playerId)
        const merged = mergeFleetPlayerWithStreamSlice(undefined, streamSlice, player.name)
        return (
          <FleetPlayerTableTile
            key={player.playerId}
            playerName={merged.playerName}
            records={merged.records}
            discrepancy={merged.discrepancy}
            componentCatalog={componentCatalog}
            streamError={merged.streamError}
            streamSlice={merged.streamSlice}
          />
        )
      })}
    </div>
  )
}
