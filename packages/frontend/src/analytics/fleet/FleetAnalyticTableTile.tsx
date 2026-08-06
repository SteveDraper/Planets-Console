import { FleetTableView } from './FleetTableView'
import type { AnalyticShellScope } from '../../api/bff'
import { useTurnRacePlayerLabels } from '../../lib/turnRacePlayerLabels'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'

type FleetAnalyticTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
  /** Demuxed fleet stream state owned above table/map view mode. */
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
}

export function FleetAnalyticTableTile({
  analyticScope,
  fetchEnabled,
  streamPlayersById,
}: FleetAnalyticTableTileProps) {
  const catalogEnabled = fetchEnabled && analyticScope != null
  const componentCatalog = useFleetComponentCatalogQuery(analyticScope, catalogEnabled)
  const racePlayerLabels = useTurnRacePlayerLabels(analyticScope, catalogEnabled)

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }

  return (
    <FleetTableView
      componentCatalog={componentCatalog}
      streamPlayersById={streamPlayersById}
      racePlayerLabels={racePlayerLabels}
    />
  )
}
