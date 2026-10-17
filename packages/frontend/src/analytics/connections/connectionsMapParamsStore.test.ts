import { beforeEach, describe, expect, it } from 'vitest'
import {
  CONNECTIONS_MAP_PARAMS_STORAGE_KEY,
  DEFAULT_CONNECTIONS_MAP_PARAMS,
  useConnectionsMapParamsStore,
} from './connectionsMapParamsStore'

describe('useConnectionsMapParamsStore', () => {
  beforeEach(() => {
    localStorage.removeItem(CONNECTIONS_MAP_PARAMS_STORAGE_KEY)
    useConnectionsMapParamsStore.setState({
      connectionsMapParams: DEFAULT_CONNECTIONS_MAP_PARAMS,
    })
  })

  it('defaults to warp 9, include flares, and flare depth 2', () => {
    expect(useConnectionsMapParamsStore.getState().connectionsMapParams).toEqual({
      warpSpeed: 9,
      gravitonicMovement: false,
      flareMode: 'include',
      flareDepth: 2,
    })
  })

  it('persists flareMode and omits the session-only knobs', () => {
    useConnectionsMapParamsStore.getState().setConnectionsMapParams({
      warpSpeed: 4,
      gravitonicMovement: true,
      flareMode: 'only',
      flareDepth: 3,
    })

    expect(useConnectionsMapParamsStore.getState().connectionsMapParams).toEqual({
      warpSpeed: 4,
      gravitonicMovement: true,
      flareMode: 'only',
      flareDepth: 3,
    })

    const raw = localStorage.getItem(CONNECTIONS_MAP_PARAMS_STORAGE_KEY)
    expect(raw).toContain('"flareMode":"only"')
    expect(raw).not.toContain('warpSpeed')
    expect(raw).not.toContain('gravitonicMovement')
    expect(raw).not.toContain('flareDepth')
  })

  it('restores flareMode on rehydrate and leaves the other knobs at defaults', async () => {
    localStorage.setItem(
      CONNECTIONS_MAP_PARAMS_STORAGE_KEY,
      JSON.stringify({
        state: {
          flareMode: 'off',
          warpSpeed: 4,
          gravitonicMovement: true,
          flareDepth: 3,
        },
        version: 1,
      }),
    )

    await useConnectionsMapParamsStore.persist.rehydrate()

    expect(useConnectionsMapParamsStore.getState().connectionsMapParams).toEqual({
      warpSpeed: 9,
      gravitonicMovement: false,
      flareMode: 'off',
      flareDepth: 2,
    })
  })

  it('falls back to include when the stored flareMode is missing or invalid', async () => {
    localStorage.setItem(
      CONNECTIONS_MAP_PARAMS_STORAGE_KEY,
      JSON.stringify({ state: { flareMode: 'sometimes' }, version: 1 }),
    )
    await useConnectionsMapParamsStore.persist.rehydrate()
    expect(useConnectionsMapParamsStore.getState().connectionsMapParams.flareMode).toBe('include')

    localStorage.setItem(
      CONNECTIONS_MAP_PARAMS_STORAGE_KEY,
      JSON.stringify({ state: {}, version: 1 }),
    )
    await useConnectionsMapParamsStore.persist.rehydrate()
    expect(useConnectionsMapParamsStore.getState().connectionsMapParams.flareMode).toBe('include')
    expect(useConnectionsMapParamsStore.getState().connectionsMapParams.warpSpeed).toBe(9)
  })
})
