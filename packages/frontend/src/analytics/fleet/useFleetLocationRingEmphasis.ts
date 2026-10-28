import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { useShellStore } from '../../stores/shell'
import { useFleetLocationRingEmphasisStore } from '../../stores/fleetLocationRingEmphasis'
import { fleetMapPaintSlices } from './fleetMapPaint'
import { collectFleetLocationRingShips, type FleetLocationRingStack } from './fleetLocationRings'
import { fleetLocationRingPaintLayers } from './fleetLocationRingEmphasis'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'
import { useFleetHoverAdmissionStream } from './useFleetHoverAdmissionStream'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

const NO_EMPHASISED_PLAYER_IDS: ReadonlySet<number> = new Set()

export type FleetLocationRingEmphasisPaint = {
  emphasisedPlayerIds: ReadonlySet<number>
  /** Emphasis-only rings for a visibility-off sidebar hover. Never merged into rest. */
  temporaryStacks: readonly FleetLocationRingStack[]
}

/**
 * Map-mode fleet location ring emphasis. Sidebar hover of a visibility-off
 * player admits that player on a side stream and paints temporary rings from
 * their ships alone. Ring hover only emphasises players already on rest rings.
 */
export function useFleetLocationRingEmphasis(
  analyticScope: AnalyticShellScope,
  fleetEnabled: boolean
): FleetLocationRingEmphasisPaint {
  const hover = useFleetLocationRingEmphasisStore((state) => state.hover)
  const viewMode = useShellStore((state) => state.viewMode)
  const { players, isPlayerVisible } = useOrderedFleetPlayers()
  const emphasisActive = fleetEnabled && viewMode === 'map' && hover != null

  const emphasisedPlayerIds = useMemo(() => {
    if (!emphasisActive || hover == null) {
      return NO_EMPHASISED_PLAYER_IDS
    }
    if (hover.kind === 'ring') {
      return new Set(hover.playerIds)
    }
    return new Set([hover.playerId])
  }, [emphasisActive, hover])

  const hiddenPlayerId =
    emphasisActive && hover?.kind === 'sidebar' && !isPlayerVisible(hover.playerId)
      ? hover.playerId
      : null

  const admitted = useFleetHoverAdmissionStream(analyticScope, hiddenPlayerId)
  const componentCatalog = useFleetComponentCatalogQuery(
    analyticScope,
    hiddenPlayerId != null
  )

  const temporaryStacks = useMemo(() => {
    if (hiddenPlayerId == null || admitted == null) {
      return []
    }
    const player = players.find((candidate) => candidate.playerId === hiddenPlayerId)
    const ships = collectFleetLocationRingShips(
      fleetMapPaintSlices(new Map([[hiddenPlayerId, admitted]])),
      [{ playerId: hiddenPlayerId, name: player?.name ?? '' }],
      componentCatalog,
      analyticScope.turn
    )
    return fleetLocationRingPaintLayers([], ships).temporaryStacks
  }, [admitted, analyticScope.turn, componentCatalog, hiddenPlayerId, players])

  return { emphasisedPlayerIds, temporaryStacks }
}
