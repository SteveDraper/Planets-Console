/**
 * Fleet descriptive **map interaction contributor**.
 * A ring hit emphasises every player with an arc on that ring.
 */

import { useEffect, useMemo, useRef } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { emphasisedPlayerIdsForRingHover } from '../../analytics/fleet/fleetLocationRingEmphasis'
import type { FleetLocationRingStack } from '../../analytics/fleet/fleetLocationRings'
import { FleetLocationRingTooltipBody } from '../../analytics/fleet/FleetLocationRingTooltipBody'
import { useFleetLocationRingEmphasisStore } from '../../stores/fleetLocationRingEmphasis'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import {
  mapHitContextFromState,
  useMapInteractionHitState,
  useMapInteractionRegistry,
} from '../mapInteractionRegistry'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import { hitTestFleetAtPointer } from './fleetHitTest'

type PendingRingEmphasis =
  | { status: 'idle' }
  | { status: 'miss' }
  | { status: 'hit'; playerIds: readonly number[] }

export function FleetMapInteractionContributor({
  stacks,
  analyticScope,
  enabled,
}: {
  stacks: readonly FleetLocationRingStack[]
  analyticScope: AnalyticShellScope
  enabled: boolean
}) {
  const hitState = useMapInteractionHitState()
  const { version } = useMapInteractionRegistry()
  const pendingEmphasisRef = useRef<PendingRingEmphasis>({ status: 'idle' })

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (!enabled || stacks.length === 0) return null
    return {
      id: 'fleet',
      role: 'fleet',
      hitTest: (hit) => {
        const result = hitTestFleetAtPointer(hit, stacks)
        if (result == null) {
          pendingEmphasisRef.current = { status: 'miss' }
          return null
        }
        pendingEmphasisRef.current = {
          status: 'hit',
          playerIds: emphasisedPlayerIdsForRingHover(result.stack),
        }
        return {
          id: `fleet:${result.stack.key}`,
          role: 'fleet',
          kind: 'descriptive',
          title: 'Fleet',
          placement: {
            mode: 'anchor',
            flowX: result.flowX,
            flowY: result.flowY,
          },
          blocks: [
            {
              type: 'rich',
              content: (
                <FleetLocationRingTooltipBody
                  stack={result.stack}
                  analyticScope={analyticScope}
                />
              ),
            },
          ],
        }
      },
    }
  }, [enabled, stacks, analyticScope])

  // Re-register when stacks identity changes so the hover engine recollects.
  useMapInteractionContributor(contributor, [stacks])

  // Apply emphasis from the latest hitTest sample (ref only -- no second geometry).
  // ``version`` re-runs after register so the first HoverEngine compose can fill the ref.
  useEffect(() => {
    const { setRingHover, clearRingHover } = useFleetLocationRingEmphasisStore.getState()
    if (contributor == null) {
      pendingEmphasisRef.current = { status: 'idle' }
      clearRingHover()
      return
    }
    const hit = mapHitContextFromState(hitState)
    if (hit == null) {
      pendingEmphasisRef.current = { status: 'idle' }
      clearRingHover()
      return
    }
    const pending = pendingEmphasisRef.current
    if (pending.status === 'hit') {
      setRingHover(pending.playerIds)
      return
    }
    if (pending.status === 'miss') {
      clearRingHover()
    }
  }, [contributor, hitState, version])

  useEffect(
    () => () => {
      useFleetLocationRingEmphasisStore.getState().clearRingHover()
    },
    []
  )

  return null
}
