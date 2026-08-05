import { afterEach, describe, expect, it } from 'vitest'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import {
  requestMapAttention,
  useMapAttentionRequestStore,
} from '../../stores/mapAttentionRequest'
import { selectHomeworldCandidateForMapAttention } from './homeworldCandidateAttention'

describe('selectHomeworldCandidateForMapAttention', () => {
  afterEach(() => {
    useHomeworldLocatorSelectionStore.getState().clearSelection()
    useMapAttentionRequestStore.getState().clearAttention()
  })

  it('sets planet selection and a homeworld map attention request', () => {
    selectHomeworldCandidateForMapAttention(42)
    expect(useHomeworldLocatorSelectionStore.getState().selection).toEqual({
      kind: 'planet',
      planetId: 42,
    })
    const pending = useMapAttentionRequestStore.getState().pending
    expect(pending).toMatchObject({
      kind: 'homeworld-planet',
      planetId: 42,
      pan: 'if-offscreen',
    })
    expect(typeof pending?.token).toBe('number')
  })

  it('re-requesting the same planet bumps the attention token', () => {
    selectHomeworldCandidateForMapAttention(7)
    const first = useMapAttentionRequestStore.getState().pending!.token
    selectHomeworldCandidateForMapAttention(7)
    const second = useMapAttentionRequestStore.getState().pending!.token
    expect(second).toBeGreaterThanOrEqual(first)
  })
})

describe('requestMapAttention', () => {
  afterEach(() => {
    useMapAttentionRequestStore.getState().clearAttention()
  })

  it('records wormhole-cell intents on the shared bus', () => {
    requestMapAttention({
      kind: 'wormhole-cell',
      mapX: 10,
      mapY: 20,
      pan: 'always',
    })
    expect(useMapAttentionRequestStore.getState().pending).toMatchObject({
      kind: 'wormhole-cell',
      mapX: 10,
      mapY: 20,
      pan: 'always',
    })
  })
})
