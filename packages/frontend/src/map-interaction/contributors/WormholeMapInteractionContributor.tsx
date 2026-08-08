/**
 * Wormhole affordance **map-element** contributor for the map interaction surface.
 *
 * Same Stellar Cartography analytic also mounts the descriptive cartography
 * sample contributor; kinds differ so composition can ``stacksWith``.
 *
 * Line reveal is driven from the hit-test result (ref → effect → store) so
 * geometry runs once per compose pass -- not again in the reveal effect.
 */

import { useEffect, useMemo, useRef } from 'react'
import type { MapEdge } from '../../api/bff'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import { useWormholeLineRevealStore } from '../../stores/wormholeLineReveal'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import {
  mapHitContextFromState,
  useMapInteractionHitState,
  useMapInteractionRegistry,
} from '../mapInteractionRegistry'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import { hitTestWormholeAtPointer } from './wormholeHitTest'

type PendingLineReveal =
  | { status: 'idle' }
  | { status: 'hit'; mapX: number; mapY: number }
  | { status: 'miss' }

export function WormholeMapInteractionContributor({
  cartography,
  hoverByCell,
  displayEdges,
}: {
  cartography: StellarCartographyMapContext | undefined
  hoverByCell: ReadonlyMap<string, WormholeEndpointHoverInfo>
  displayEdges: readonly MapEdge[]
}) {
  const hitState = useMapInteractionHitState()
  const { version } = useMapInteractionRegistry()
  const wasHittingRef = useRef(false)
  const pendingRevealRef = useRef<PendingLineReveal>({ status: 'idle' })

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (cartography == null) return null
    if (!cartography.policy.areWormholesShown()) return null
    return {
      id: 'wormhole',
      role: 'wormhole',
      hitTest: (hit) => {
        const result = hitTestWormholeAtPointer(hit, hoverByCell, displayEdges)
        if (result == null) {
          pendingRevealRef.current = { status: 'miss' }
          return null
        }
        pendingRevealRef.current = {
          status: 'hit',
          mapX: result.revealMapX,
          mapY: result.revealMapY,
        }
        return {
          id: result.id,
          role: 'wormhole',
          kind: 'map-element',
          title: 'Wormhole',
          placement: result.placement,
          blocks: [{ type: 'lines', lines: result.lines }],
        }
      },
    }
  }, [cartography, hoverByCell, displayEdges])

  useMapInteractionContributor(contributor)

  // Apply reveal from the latest hitTest sample (ref only -- no second geometry).
  // ``version`` re-runs after register so the first HoverEngine compose can fill the ref.
  useEffect(() => {
    const { revealAt, scheduleClear, cancelClear } =
      useWormholeLineRevealStore.getState()

    const clearIfWasHitting = () => {
      if (!wasHittingRef.current) return
      wasHittingRef.current = false
      scheduleClear()
    }

    if (contributor == null) {
      pendingRevealRef.current = { status: 'idle' }
      clearIfWasHitting()
      return
    }
    const hit = mapHitContextFromState(hitState)
    if (hit == null) {
      pendingRevealRef.current = { status: 'idle' }
      clearIfWasHitting()
      return
    }

    const pending = pendingRevealRef.current
    if (pending.status === 'hit') {
      wasHittingRef.current = true
      cancelClear()
      revealAt(pending.mapX, pending.mapY)
      return
    }
    if (pending.status === 'miss') {
      clearIfWasHitting()
    }
  }, [contributor, hitState, version])

  return null
}
