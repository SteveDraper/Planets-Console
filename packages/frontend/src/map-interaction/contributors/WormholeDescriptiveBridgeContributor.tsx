/**
 * Wormhole hover *lines* as a descriptive contribution (bridge until #293
 * reclassifies wormhole affordances as map-element).
 */

import { useMemo } from 'react'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import { useWormholeInteractionState } from '../../components/map-graph/stellarCartographyWormholeInteraction'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'

export function WormholeDescriptiveBridgeContributor({
  cartography,
}: {
  cartography: StellarCartographyMapContext | undefined
}) {
  const { wormholeHoverLines } = useWormholeInteractionState()

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (cartography == null) return null
    if (!cartography.policy.areWormholesShown()) return null
    if (wormholeHoverLines == null || wormholeHoverLines.length === 0) return null
    const lines = wormholeHoverLines
    return {
      id: 'wormhole',
      role: 'wormhole',
      hitTest: () => ({
        id: 'wormhole',
        role: 'wormhole',
        kind: 'descriptive',
        title: 'Wormhole',
        placement: { mode: 'cursor' },
        blocks: [{ type: 'lines', lines }],
      }),
    }
  }, [cartography, wormholeHoverLines])

  useMapInteractionContributor(contributor)
  return null
}
