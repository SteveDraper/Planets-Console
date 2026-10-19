import { beforeEach, describe, expect, it } from 'vitest'
import { useFleetLocationRingEmphasisStore } from './fleetLocationRingEmphasis'

describe('useFleetLocationRingEmphasisStore', () => {
  beforeEach(() => {
    useFleetLocationRingEmphasisStore.setState({ hover: null })
  })

  it('clears ring hover without dropping a sidebar hover', () => {
    const store = useFleetLocationRingEmphasisStore.getState()
    store.setSidebarHover(4)
    store.clearRingHover()
    expect(useFleetLocationRingEmphasisStore.getState().hover).toEqual({
      kind: 'sidebar',
      playerId: 4,
    })
  })

  it('clears a sidebar hover only for that player', () => {
    const store = useFleetLocationRingEmphasisStore.getState()
    store.setRingHover([2, 1])
    store.clearSidebarHover(1)
    expect(useFleetLocationRingEmphasisStore.getState().hover).toEqual({
      kind: 'ring',
      playerIds: [1, 2],
    })
    store.setSidebarHover(4)
    store.clearSidebarHover(9)
    expect(useFleetLocationRingEmphasisStore.getState().hover).toEqual({
      kind: 'sidebar',
      playerId: 4,
    })
    store.clearSidebarHover(4)
    expect(useFleetLocationRingEmphasisStore.getState().hover).toBeNull()
  })
})
