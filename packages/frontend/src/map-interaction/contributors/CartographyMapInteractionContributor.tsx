/**
 * Stellar Cartography sample descriptive **map interaction contributor**.
 * Async fetch is manager-owned via the surface async slot.
 */

import { useMemo } from 'react'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import {
  cartographySampleRequestKey,
  fetchCartographySampleBlocks,
} from './cartographyHitTest'

export function CartographyMapInteractionContributor({
  cartography,
}: {
  cartography: StellarCartographyMapContext | undefined
}) {
  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (cartography == null) return null
    return {
      id: 'cartography',
      role: 'cartography',
      hitTest: (hit) => {
        const requestKey = cartographySampleRequestKey(hit)
        if (requestKey == null) return null
        return {
          id: `cartography:${requestKey}`,
          role: 'cartography',
          kind: 'descriptive',
          title: 'Stellar Cartography',
          placement: { mode: 'cursor' },
          blocks: [
            {
              type: 'async',
              requestKey,
              status: 'pending',
            },
          ],
        }
      },
      fetch: (hit) => fetchCartographySampleBlocks(hit, cartography),
    }
  }, [cartography])

  useMapInteractionContributor(contributor)
  return null
}
