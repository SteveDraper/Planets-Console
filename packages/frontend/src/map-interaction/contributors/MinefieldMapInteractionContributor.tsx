/**
 * Minefield descriptive **map interaction contributor**.
 */

import { useMemo } from 'react'
import type { CombinedMapData } from '../../api/bff'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import {
  formatMinefieldHoverLines,
  knownMinefieldsAtPoint,
} from '../../analytics/minefields/minefieldHitTest'
import { type MinefieldTypeId } from '../../analytics/minefields/types'
import { useMinefieldsPreferencesStore } from '../../stores/minefieldsPreferences'
import { clientToFlowPosition } from '../../lib/mapFlowGeometry'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'

export function MinefieldMapInteractionContributor({
  minefields,
  roster,
  shellTurn,
  enabled,
}: {
  minefields: CombinedMapData['minefields']
  roster: readonly PerspectiveRow[]
  shellTurn: number
  enabled: boolean
}) {
  const types = useMinefieldsPreferencesStore((s) => s.types)
  const enabledTypes = useMemo(() => {
    const set = new Set<MinefieldTypeId>()
    for (const typeId of ['normal', 'web'] as const) {
      if (types[typeId].enabled) set.add(typeId)
    }
    return set
  }, [types])

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (!enabled || minefields.length === 0) return null
    return {
      id: 'minefield',
      role: 'minefield',
      hitTest: (hit) => {
        const flow = clientToFlowPosition(
          hit.clientPos.x,
          hit.clientPos.y,
          hit.domNode,
          hit.transform
        )
        if (flow == null) return null
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        const hits = knownMinefieldsAtPoint(minefields, px, py, enabledTypes)
        if (hits.length === 0) return null
        return {
          id: `minefield:${hits.map((f) => f.id).join(',')}`,
          role: 'minefield',
          kind: 'descriptive',
          title: 'Minefields',
          placement: { mode: 'cursor' },
          blocks: [
            {
              type: 'lines',
              lines: formatMinefieldHoverLines(hits, roster, shellTurn),
            },
          ],
        }
      },
    }
  }, [enabled, minefields, enabledTypes, roster, shellTurn])

  useMapInteractionContributor(contributor, [minefields, enabledTypes, roster, shellTurn])

  return null
}
