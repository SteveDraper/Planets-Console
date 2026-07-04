import type { AnalyticShellScope } from '../../api/bff'
import { FleetTableView } from './FleetTableView'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'
import { useFleetTableStream } from './useFleetTableStream'

type FleetAnalyticTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

export function FleetAnalyticTableTile({
  analyticScope,
  fetchEnabled,
}: FleetAnalyticTableTileProps) {
  const streamEnabled = fetchEnabled && analyticScope != null
  const componentCatalog = useFleetComponentCatalogQuery(analyticScope, streamEnabled)
  const { streamPlayersById } = useFleetTableStream(analyticScope, streamEnabled)

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }

  return (
    <FleetTableView componentCatalog={componentCatalog} streamPlayersById={streamPlayersById} />
  )
}
