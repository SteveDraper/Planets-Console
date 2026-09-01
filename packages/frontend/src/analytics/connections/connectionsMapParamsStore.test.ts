import { beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_CONNECTIONS_MAP_PARAMS,
  useConnectionsMapParamsStore,
} from './connectionsMapParamsStore'

describe('useConnectionsMapParamsStore', () => {
  beforeEach(() => {
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

  it('updates params in memory without persist middleware', () => {
    useConnectionsMapParamsStore.getState().setConnectionsMapParams({
      ...DEFAULT_CONNECTIONS_MAP_PARAMS,
      warpSpeed: 4,
    })
    expect(useConnectionsMapParamsStore.getState().connectionsMapParams.warpSpeed).toBe(4)
    expect('persist' in useConnectionsMapParamsStore).toBe(false)
  })
})
