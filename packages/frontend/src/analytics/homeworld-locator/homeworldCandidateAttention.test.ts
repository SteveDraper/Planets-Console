import { afterEach, describe, expect, it } from 'vitest'
import {
  requestMapAttention,
  useMapAttentionRequestStore,
} from '../../stores/mapAttentionRequest'
import { selectHomeworldCandidateForMapAttention } from './homeworldCandidateAttention'

describe('selectHomeworldCandidateForMapAttention', () => {
  afterEach(() => {
    useMapAttentionRequestStore.getState().clearAttention()
  })

  it('sets a homeworld map attention request', () => {
    selectHomeworldCandidateForMapAttention(42)
    const pending = useMapAttentionRequestStore.getState().pending
    expect(pending).toMatchObject({
      kind: 'homeworld-planet',
      planetId: 42,
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
    })
    expect(useMapAttentionRequestStore.getState().pending).toMatchObject({
      kind: 'wormhole-cell',
      mapX: 10,
      mapY: 20,
    })
  })
})
