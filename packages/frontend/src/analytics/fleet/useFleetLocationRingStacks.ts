import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
  type FleetLocationRingStack,
} from './fleetLocationRings'
import { useFleetStreamPlayersById } from './FleetStreamPlayersContext'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

/** Project the shared fleet stream into location-ring stacks for map paint/hover. */
export function useFleetLocationRingStacks(
  analyticScope: AnalyticShellScope,
  enabled: boolean
): readonly FleetLocationRingStack[] {
  const streamPlayersById = useFleetStreamPlayersById()
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })
  const componentCatalog = useFleetComponentCatalogQuery(analyticScope, enabled)

  return useMemo(() => {
    if (!enabled) {
      return []
    }
    const ships = collectFleetLocationRingShips(
      streamPlayersById,
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
    streamPlayersById,
    visiblePlayers,
    componentCatalog,
    analyticScope.turn,
  ])
}
