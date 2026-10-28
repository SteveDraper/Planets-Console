import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
  type FleetLocationRingStack,
} from './fleetLocationRings'
import { fleetMapPaintSlices } from './fleetMapPaint'
import { useFleetStreamPlayersById } from './FleetStreamPlayersContext'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

/** Project each player's held map picture into location-ring stacks. */
export function useFleetLocationRingStacks(
  analyticScope: AnalyticShellScope,
  enabled: boolean
): readonly FleetLocationRingStack[] {
  const streamPlayersById = useFleetStreamPlayersById()
  const mapPlayersById = useMemo(
    () => fleetMapPaintSlices(streamPlayersById),
    [streamPlayersById]
  )
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })
  const componentCatalog = useFleetComponentCatalogQuery(analyticScope, enabled)

  return useMemo(() => {
    if (!enabled) {
      return []
    }
    const ships = collectFleetLocationRingShips(
      mapPlayersById,
      visiblePlayers.map((player) => ({
        playerId: player.playerId,
        name: player.name,
      })),
      componentCatalog,
      analyticScope.turn
    )
    return buildFleetLocationRingStacks(ships, FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE)
  }, [
    enabled,
    mapPlayersById,
    visiblePlayers,
    componentCatalog,
    analyticScope.turn,
  ])
}
