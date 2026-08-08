/**
 * Wormhole affordance **map-element** contributor for the map interaction surface.
 *
 * Same Stellar Cartography analytic also mounts the descriptive cartography
 * sample contributor; kinds differ so composition can ``stacksWith``.
 */

import { useEffect, useMemo, useRef } from 'react'
import type { MapEdge } from '../../api/bff'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import { useWormholeLineReveal } from '../../components/map-graph/stellarCartographyWormholeInteraction'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import type { MapHoverContribution } from '../mapHoverContributionTypes'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import {
  mapHitContextFromState,
  useMapInteractionHitState,
} from '../mapInteractionRegistry'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import { hitTestWormholeAtPointer } from './wormholeHitTest'

function wormholeMapElementContribution(
  hit: Parameters<typeof hitTestWormholeAtPointer>[0],
  hoverByCell: ReadonlyMap<string, WormholeEndpointHoverInfo>,
  displayEdges: readonly MapEdge[]
): MapHoverContribution | null {
  const result = hitTestWormholeAtPointer(hit, hoverByCell, displayEdges)
  if (result == null) return null
  return {
    id: result.id,
    role: 'wormhole',
    kind: 'map-element',
    title: 'Wormhole',
    placement: result.placement,
    blocks: [{ type: 'lines', lines: result.lines }],
  }
}

export function WormholeMapInteractionContributor({
  cartography,
  hoverByCell,
  displayEdges,
}: {
  cartography: StellarCartographyMapContext | undefined
  hoverByCell: ReadonlyMap<string, WormholeEndpointHoverInfo>
  displayEdges: readonly MapEdge[]
}) {
  const lineReveal = useWormholeLineReveal()
  const hitState = useMapInteractionHitState()
  const wasHittingRef = useRef(false)

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (cartography == null) return null
    if (!cartography.policy.areWormholesShown()) return null
    return {
      id: 'wormhole',
      role: 'wormhole',
      hitTest: (hit) =>
        wormholeMapElementContribution(hit, hoverByCell, displayEdges),
    }
  }, [cartography, hoverByCell, displayEdges])

  useMapInteractionContributor(contributor)

  // Drive on-hover line reveal from the same hit as map-element chrome (no paint capture).
  useEffect(() => {
    const clearIfWasHitting = () => {
      if (!wasHittingRef.current) return
      wasHittingRef.current = false
      lineReveal.scheduleClear()
    }

    if (contributor == null) {
      clearIfWasHitting()
      return
    }
    const hit = mapHitContextFromState(hitState)
    if (hit == null) {
      clearIfWasHitting()
      return
    }
    const result = hitTestWormholeAtPointer(hit, hoverByCell, displayEdges)
    if (result == null) {
      clearIfWasHitting()
      return
    }
    wasHittingRef.current = true
    lineReveal.cancelClear()
    lineReveal.revealAt(result.revealMapX, result.revealMapY)
  }, [contributor, hitState, hoverByCell, displayEdges, lineReveal])

  return null
}
