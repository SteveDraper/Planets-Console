import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import { StellarCartographyHoverPanel } from './StellarCartographyHoverPanel'
import type { StellarCartographyMapContext } from './mapUiConfig'
import { cartographyVisibilityPolicy } from './cartographyVisibilityPolicy'
import { defaultStellarCartographyMapUiConfig } from './mapUiConfig'
import { defaultCartographyLayerVisibility } from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import { defaultWormholeDisplayMode } from './wormholeDisplayMode'

const pane = document.createElement('div')
pane.getBoundingClientRect = () =>
  ({
    left: 0,
    top: 0,
    right: 100,
    bottom: 100,
    width: 100,
    height: 100,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }) as DOMRect

vi.mock('@xyflow/react', () => ({
  useStore: (
    selector: (s: {
      domNode: HTMLElement | null
      transform: [number, number, number]
    }) => unknown
  ) => selector({ domNode: pane, transform: [0, 0, 1] }),
}))

vi.mock('../../api/bff', () => ({
  fetchStellarCartographySample: vi.fn(() =>
    Promise.resolve({ entries: [] as { layer: string; lines: string[] }[] })
  ),
}))

vi.mock('../../lib/planetSpatialGrid', () => ({
  flowToMapCellIndices: () => ({ mapX: 1, mapY: 2 }),
}))

const settingsGates = {
  debrisDiskBorders: true,
  starClusters: true,
  neutronClusters: true,
  nebulae: true,
  ionStorms: true,
  wormholes: true,
  blackHoles: true,
}

const cartography = {
  config: defaultStellarCartographyMapUiConfig(),
  analyticScope: {
    gameId: '1',
    turn: 1,
    perspective: 1,
  },
  policy: cartographyVisibilityPolicy({
    ...defaultStellarCartographyMapUiConfig(),
    settingsGates,
    wormholeDisplayMode: defaultWormholeDisplayMode(),
    starClusterDisplayMode: defaultStarClusterDisplayMode(),
    neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
    layerVisibility: defaultCartographyLayerVisibility(),
  }),
} as StellarCartographyMapContext

describe('StellarCartographyHoverPanel shared pointer', () => {
  beforeEach(() => {
    vi.spyOn(pane, 'addEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not attach pane pointer listeners when clientPos is shared', () => {
    render(
      <StellarCartographyHoverPanel
        cartography={cartography}
        wormholeHoverLines={null}
        clientPos={{ x: 40, y: 50 }}
        additionalHoverLines={['region line']}
        clientToFlowPosition={() => ({ x: 40, y: 50 })}
      />
    )

    expect(pane.addEventListener).not.toHaveBeenCalled()
  })
})
