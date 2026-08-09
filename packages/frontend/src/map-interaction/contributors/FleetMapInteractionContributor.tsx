/**
 * Fleet descriptive **map interaction contributor**.
 */

import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import type { FleetLocationRingStack } from '../../analytics/fleet/fleetLocationRings'
import { FleetLocationRingTooltipBody } from '../../analytics/fleet/FleetLocationRingTooltipBody'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import { hitTestFleetAtPointer } from './fleetHitTest'

export function FleetMapInteractionContributor({
  stacks,
  analyticScope,
  enabled,
}: {
  stacks: readonly FleetLocationRingStack[]
  analyticScope: AnalyticShellScope
  enabled: boolean
}) {
  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (!enabled || stacks.length === 0) return null
    return {
      id: 'fleet',
      role: 'fleet',
      hitTest: (hit) => {
        const result = hitTestFleetAtPointer(hit, stacks)
        if (result == null) return null
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

  // Re-register when stacks change so the hover engine recollects (version bump).
  useMapInteractionContributor(contributor, stacks)

  return null
}
