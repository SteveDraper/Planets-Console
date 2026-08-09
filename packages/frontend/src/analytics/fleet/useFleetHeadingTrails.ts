import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { useFleetHeadingTrailExtendStore } from '../../stores/fleetHeadingTrailExtend'
import {
  collectFleetHeadingTrails,
  type FleetHeadingTrail,
} from './fleetHeadingTrails'
import { useFleetStreamPlayersById } from './FleetStreamPlayersContext'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

/** Project the shared fleet stream into heading trail segments for map paint. */
export function useFleetHeadingTrails(
  analyticScope: AnalyticShellScope,
  enabled: boolean
): readonly FleetHeadingTrail[] {
  const streamPlayersById = useFleetStreamPlayersById()
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })
  const extendTurns = useFleetHeadingTrailExtendStore((state) => state.extendTurns)

  return useMemo(() => {
    if (!enabled) {
      return []
    }
    return collectFleetHeadingTrails(
      streamPlayersById,
      visiblePlayers.map((player) => ({
        playerId: player.playerId,
        name: player.name,
      })),
      analyticScope.turn,
      extendTurns
    )
  }, [enabled, streamPlayersById, visiblePlayers, analyticScope.turn, extendTurns])
}
