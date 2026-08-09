import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  collectFleetHeadingTrails,
  type FleetHeadingTrail,
} from './fleetHeadingTrails'
import { useFleetStreamPlayersById } from './FleetStreamPlayersContext'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

/** Project the shared fleet stream into current-turn heading trails for map paint. */
export function useFleetHeadingTrails(
  analyticScope: AnalyticShellScope,
  enabled: boolean
): readonly FleetHeadingTrail[] {
  const streamPlayersById = useFleetStreamPlayersById()
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })

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
      analyticScope.turn
    )
  }, [enabled, streamPlayersById, visiblePlayers, analyticScope.turn])
}
