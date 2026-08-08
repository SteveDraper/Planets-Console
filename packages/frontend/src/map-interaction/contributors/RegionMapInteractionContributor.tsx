/**
 * Region overlay descriptive **map interaction contributor**.
 */

import { useMemo } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import { hitTestRegionLinesAtPointer } from './regionHitTest'

export function RegionMapInteractionContributor({
  regionOverlays,
}: {
  regionOverlays: readonly MapRegionOverlay[]
}) {
  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (regionOverlays.length === 0) return null
    return {
      id: 'region',
      role: 'region',
      hitTest: (hit) => {
        const lines = hitTestRegionLinesAtPointer(hit, regionOverlays)
        if (lines.length === 0) return null
        return {
          id: 'region',
          role: 'region',
          kind: 'descriptive',
          title: 'Region',
          placement: { mode: 'cursor' },
          blocks: [{ type: 'lines', lines }],
        }
      },
    }
  }, [regionOverlays])

  useMapInteractionContributor(contributor)
  return null
}
