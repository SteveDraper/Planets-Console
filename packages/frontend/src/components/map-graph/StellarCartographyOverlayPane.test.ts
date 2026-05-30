import { describe, expect, it } from 'vitest'
import { collectWormholeEndpoints } from './StellarCartographyOverlayPane'
import type { CombinedMapData } from '../../api/bff'

describe('collectWormholeEndpoints', () => {
  it('dedupes rendered wormhole nodes and unknown entrances', () => {
    const nodes = [
      { id: 'stellar-cartography:wh-1', label: '', x: 10, y: 20 },
      { id: 'stellar-cartography:wh-2', label: '', x: 10, y: 20 },
      { id: 'base-map:planet-1', label: 'Planet', x: 30, y: 40 },
    ] satisfies CombinedMapData['nodes']
    const unknownEntrances = [
      { x: 10, y: 20 },
      { x: 50, y: 60 },
    ] satisfies CombinedMapData['wormholeUnknownEntrances']

    expect(collectWormholeEndpoints(nodes, unknownEntrances)).toEqual([
      { x: 10, y: 20 },
      { x: 50, y: 60 },
    ])
  })
})
