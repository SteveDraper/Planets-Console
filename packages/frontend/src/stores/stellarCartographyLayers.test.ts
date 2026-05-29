import { beforeEach, describe, expect, it } from 'vitest'
import { defaultCartographyLayerVisibility } from '../analytics/stellar-cartography/layers'
import { defaultWormholeDisplayMode } from '../analytics/stellar-cartography/wormholeDisplayMode'
import {
  STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY,
  useStellarCartographyLayersStore,
} from '../stores/stellarCartographyLayers'

describe('useStellarCartographyLayersStore', () => {
  beforeEach(() => {
    localStorage.removeItem(STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY)
    useStellarCartographyLayersStore.setState({
      layers: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: defaultWormholeDisplayMode(),
    })
  })

  it('defaults non-wormhole layers to enabled and wormholes to always', () => {
    expect(useStellarCartographyLayersStore.getState().layers).toEqual(
      defaultCartographyLayerVisibility()
    )
    expect(useStellarCartographyLayersStore.getState().wormholeDisplayMode).toBe('always')
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

  it('persists layer toggles to localStorage', () => {
    useStellarCartographyLayersStore.getState().setLayerEnabled('black-holes', false)
    const raw = localStorage.getItem(STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('black-holes')
    expect(raw).toContain('false')
  })
})
