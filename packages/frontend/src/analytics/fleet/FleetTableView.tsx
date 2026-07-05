import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetComponentCatalog } from './fleetComponentCatalog'
import { EMPTY_FLEET_COMPONENT_CATALOG } from './fleetComponentCatalog'
import { fleetPlayerDisplayLabel } from './fleetPlayerDisplayLabel'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

type FleetTableViewProps = {
  componentCatalog?: FleetComponentCatalog
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
  racePlayerLabels: Map<number, string>
}

export function FleetTableView({
  componentCatalog = EMPTY_FLEET_COMPONENT_CATALOG,
  streamPlayersById,
  racePlayerLabels,
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
        const merged = fleetPlayerFromStreamSlice(streamSlice, player.name)
        const playerLabel = fleetPlayerDisplayLabel(player, racePlayerLabels, streamSlice)
        return (
          <FleetPlayerTableTile
            key={player.playerId}
            playerName={playerLabel}
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
