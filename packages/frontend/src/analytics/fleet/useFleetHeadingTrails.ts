import { useMemo } from 'react'
import type { AnalyticShellScope, MapNode } from '../../api/bff'
import { useFleetHeadingTrailExtendStore } from '../../stores/fleetHeadingTrailExtend'
import {
  collectFleetHeadingTrails,
  fleetHeadingTrailsEnabledForShell,
  type FleetHeadingTrail,
} from './fleetHeadingTrails'
import { fleetTrailPlanetStopsFromMapNodes } from './fleetTrailPlanetStopsFromMapNodes'
import { fleetMapPaintSlices } from './fleetMapPaint'
import { useFleetStreamPlayersById } from './FleetStreamPlayersContext'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

/** Project each player's held map picture into heading trail segments. */
export function useFleetHeadingTrails(
  analyticScope: AnalyticShellScope,
  enabled: boolean,
  planetMapNodes: readonly MapNode[] = [],
  futureTurnOffset: number = 0
): readonly FleetHeadingTrail[] {
  const streamPlayersById = useFleetStreamPlayersById()
  const mapPlayersById = useMemo(
    () => fleetMapPaintSlices(streamPlayersById),
    [streamPlayersById]
  )
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })
  const extendTurns = useFleetHeadingTrailExtendStore((state) => state.extendTurns)
  const planets = useMemo(
    () => fleetTrailPlanetStopsFromMapNodes(planetMapNodes),
    [planetMapNodes]
  )
  const trailsEnabled = fleetHeadingTrailsEnabledForShell(enabled, futureTurnOffset)

  return useMemo(() => {
    if (!trailsEnabled) {
      return []
    }
    return collectFleetHeadingTrails(
      mapPlayersById,
      visiblePlayers.map((player) => ({
        playerId: player.playerId,
        name: player.name,
      })),
      analyticScope.turn,
      extendTurns,
      planets
    )
  }, [
    trailsEnabled,
    mapPlayersById,
    visiblePlayers,
    analyticScope.turn,
    extendTurns,
    planets,
  ])
}
