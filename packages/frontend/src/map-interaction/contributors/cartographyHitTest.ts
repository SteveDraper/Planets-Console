/**
 * Cartography sample descriptive hit-test / fetch for the **map interaction surface**.
 */

import {
  fetchStellarCartographySample,
  type StellarCartographySampleEntry,
} from '../../api/bff'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import { formatStellarCartographySampleLine } from '../../analytics/stellar-cartography/sampleTooltipFormat'
import { flowToMapCellIndices } from '../../lib/planetSpatialGrid'
import { clientToFlowPosition } from '../../lib/mapFlowGeometry'
import type { MapHitContext } from '../mapInteractionContributorTypes'
import type { MapHoverSyncBlock } from '../mapHoverContributionTypes'

export function cartographySampleRequestKey(hit: MapHitContext): string | null {
  if (hit.domNode == null || hit.transform == null) return null
  const flow = clientToFlowPosition(
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
  if (flow == null) return null
  const { mapX, mapY } = flowToMapCellIndices(flow.x, flow.y)
  return `${mapX}:${mapY}`
}

export function cartographySampleLinesFromEntries(
  entries: readonly StellarCartographySampleEntry[],
  cartography: StellarCartographyMapContext
): string[] {
  return cartography.policy
    .sampleEntries([...entries])
    .map(formatStellarCartographySampleLine)
}

export async function fetchCartographySampleBlocks(
  hit: MapHitContext,
  cartography: StellarCartographyMapContext
): Promise<readonly MapHoverSyncBlock[]> {
  const key = cartographySampleRequestKey(hit)
  if (key == null) return []
  const [mapXRaw, mapYRaw] = key.split(':')
  const mapX = Number(mapXRaw)
  const mapY = Number(mapYRaw)
  if (!Number.isFinite(mapX) || !Number.isFinite(mapY)) return []
  try {
    const data = await fetchStellarCartographySample(
      cartography.analyticScope,
      mapX,
      mapY
    )
    const lines = cartographySampleLinesFromEntries(data.entries, cartography)
    if (lines.length === 0) return []
    return [{ type: 'lines', lines }]
  } catch {
    return []
  }
}
