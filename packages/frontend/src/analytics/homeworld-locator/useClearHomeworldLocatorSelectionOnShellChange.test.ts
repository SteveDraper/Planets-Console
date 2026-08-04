import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import {
  useClearHomeworldLocatorSelectionOnShellChange,
  type HomeworldLocatorShellIdentity,
} from './useClearHomeworldLocatorSelectionOnShellChange'

const baseIdentity: HomeworldLocatorShellIdentity = {
  gameId: '628580',
  turn: 8,
  perspective: 1,
}

describe('useClearHomeworldLocatorSelectionOnShellChange', () => {
  beforeEach(() => {
    useHomeworldLocatorSelectionStore.setState({ selection: null })
    useHomeworldCandidateFlashStore.setState({ flashTarget: null })
  })

  function mountWithIdentity(identity: HomeworldLocatorShellIdentity) {
    return renderHook(
      ({ shellIdentity }) => useClearHomeworldLocatorSelectionOnShellChange(shellIdentity),
      { initialProps: { shellIdentity: identity } }
    )
  }

  it('clears selection when game id changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useHomeworldLocatorSelectionStore
      .getState()
      .setSelection({ kind: 'planet', planetId: 42 })
    expect(useHomeworldLocatorSelectionStore.getState().selection).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, gameId: '999999' } })
    expect(useHomeworldLocatorSelectionStore.getState().selection).toBeNull()
  })

  it('clears selection when turn changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useHomeworldLocatorSelectionStore
      .getState()
      .setSelection({ kind: 'sector', sectorIndex: 3 })
    expect(useHomeworldLocatorSelectionStore.getState().selection).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, turn: 9 } })
    expect(useHomeworldLocatorSelectionStore.getState().selection).toBeNull()
  })

  it('clears selection and flash when perspective changes', () => {
    const { rerender } = mountWithIdentity(baseIdentity)
    useHomeworldLocatorSelectionStore
      .getState()
      .setSelection({ kind: 'planet', planetId: 7 })
    useHomeworldCandidateFlashStore.getState().flashPlanet(7)
    expect(useHomeworldLocatorSelectionStore.getState().selection).not.toBeNull()
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).not.toBeNull()

    rerender({ shellIdentity: { ...baseIdentity, perspective: 2 } })
    expect(useHomeworldLocatorSelectionStore.getState().selection).toBeNull()
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).toBeNull()
  })
})
