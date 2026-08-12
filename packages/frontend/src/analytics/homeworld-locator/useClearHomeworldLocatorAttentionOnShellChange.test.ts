import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useMapAttentionRequestStore } from '../../stores/mapAttentionRequest'
import {
  useClearHomeworldLocatorAttentionOnShellChange,
  type HomeworldLocatorShellIdentity,
} from './useClearHomeworldLocatorAttentionOnShellChange'

const baseIdentity: HomeworldLocatorShellIdentity = {
  gameId: '628580',
  turn: 8,
  perspective: 1,
}

describe('useClearHomeworldLocatorAttentionOnShellChange', () => {
  beforeEach(() => {
    useMapAttentionRequestStore.setState({ pending: null })
  })

  function mountWithIdentity(identity: HomeworldLocatorShellIdentity) {
    return renderHook(
      ({ shellIdentity }) => useClearHomeworldLocatorAttentionOnShellChange(shellIdentity),
      { initialProps: { shellIdentity: identity } }
    )
  }

  it('clears map attention when game id changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useMapAttentionRequestStore.getState().requestAttention({
      kind: 'homeworld-planet',
      planetId: 42,
    })
    expect(useMapAttentionRequestStore.getState().pending).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, gameId: '999999' } })
    expect(useMapAttentionRequestStore.getState().pending).toBeNull()
  })

  it('clears map attention when turn changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useMapAttentionRequestStore.getState().requestAttention({
      kind: 'homeworld-planet',
      planetId: 7,
    })
    expect(useMapAttentionRequestStore.getState().pending).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, turn: 9 } })
    expect(useMapAttentionRequestStore.getState().pending).toBeNull()
  })

  it('clears map attention when perspective changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useMapAttentionRequestStore.getState().requestAttention({
      kind: 'homeworld-planet',
      planetId: 7,
    })
    expect(useMapAttentionRequestStore.getState().pending).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, perspective: 2 } })
    expect(useMapAttentionRequestStore.getState().pending).toBeNull()
  })
})
