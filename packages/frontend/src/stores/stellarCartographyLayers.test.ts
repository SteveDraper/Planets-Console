import { beforeEach, describe, expect, it } from 'vitest'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  migratePersistedClusterLayers,
} from '../analytics/stellar-cartography/clusterOutlineDisplayMode'
import { defaultWormholeDisplayMode } from '../analytics/stellar-cartography/wormholeDisplayMode'
import {
  STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY,
  useStellarCartographyLayersStore,
} from './stellarCartographyLayers'
import { defaultCartographyLayerVisibility } from '../analytics/stellar-cartography/layers'

describe('useStellarCartographyLayersStore', () => {
  beforeEach(() => {
    localStorage.removeItem(STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY)
    useStellarCartographyLayersStore.setState({
      layers: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: defaultWormholeDisplayMode(),
      starClusterDisplayMode: defaultStarClusterDisplayMode(),
      neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
    })
  })

  it('defaults non-wormhole layers to enabled and wormholes to always', () => {
    expect(useStellarCartographyLayersStore.getState().layers).toEqual(
      defaultCartographyLayerVisibility()
    )
    expect(useStellarCartographyLayersStore.getState().wormholeDisplayMode).toBe('always')
    expect(useStellarCartographyLayersStore.getState().starClusterDisplayMode).toBe('outlined')
    expect(useStellarCartographyLayersStore.getState().neutronClusterDisplayMode).toBe('outlined')
  })

  it('updates individual layer toggles', () => {
    useStellarCartographyLayersStore.getState().setLayerEnabled('nebulae', false)
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('nebulae')).toBe(false)
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('wormholes')).toBe(true)
  })

  it('updates wormhole display mode', () => {
    useStellarCartographyLayersStore.getState().setWormholeDisplayMode('on-hover')
    expect(useStellarCartographyLayersStore.getState().wormholeDisplayMode).toBe('on-hover')
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('wormholes')).toBe(true)
    useStellarCartographyLayersStore.getState().setWormholeDisplayMode('off')
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('wormholes')).toBe(false)
  })

  it('updates star and neutron cluster display modes independently', () => {
    useStellarCartographyLayersStore.getState().setStarClusterDisplayMode('no-outline')
    useStellarCartographyLayersStore.getState().setNeutronClusterDisplayMode('off')
    expect(useStellarCartographyLayersStore.getState().starClusterDisplayMode).toBe('no-outline')
    expect(useStellarCartographyLayersStore.getState().neutronClusterDisplayMode).toBe('off')
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('star-clusters')).toBe(true)
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('neutron-clusters')).toBe(
      false
    )
  })

  it('persists layer toggles to localStorage', () => {
    useStellarCartographyLayersStore.getState().setLayerEnabled('black-holes', false)
    const raw = localStorage.getItem(STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('black-holes')
    expect(raw).toContain('false')
  })
})

describe('migratePersistedClusterLayers', () => {
  it('maps legacy boolean layer toggles to outlined or off', () => {
    const migrated = migratePersistedClusterLayers(
      { 'star-clusters': false, 'neutron-clusters': true },
      undefined,
      undefined
    )
    expect(migrated.layers).toEqual({})
    expect(migrated.starClusterDisplayMode).toBe('off')
    expect(migrated.neutronClusterDisplayMode).toBe('outlined')
  })
})
