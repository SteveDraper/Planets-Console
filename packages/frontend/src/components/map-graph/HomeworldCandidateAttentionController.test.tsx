import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HOMEWORLD_CANDIDATE_FLASH_MS } from '../../analytics/homeworld-locator/constants'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { HomeworldCandidateAttentionController } from './HomeworldCandidateAttentionController'

const setViewport = vi.fn()
const getViewport = vi.fn(() => ({ x: 0, y: 0, zoom: 1 }))

const mockPane = {
  getBoundingClientRect: () => ({ width: 800, height: 600, x: 0, y: 0 }),
} as HTMLElement

let mockDomNode: HTMLElement | null = mockPane

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({ getViewport, setViewport }),
  useStore: (selector: (s: { domNode: HTMLElement | null }) => unknown) =>
    selector({
      domNode: mockDomNode,
    }),
}))

const offScreenMarkers = [{ planetId: 42, x: 10_000, y: 10_000 }] as const

describe('HomeworldCandidateAttentionController', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useHomeworldCandidateFlashStore.setState({ flashTarget: null })
    mockDomNode = mockPane
    setViewport.mockClear()
    getViewport.mockClear()
    getViewport.mockReturnValue({ x: 0, y: 0, zoom: 1 })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('clears flash store on unmount', () => {
    useHomeworldCandidateFlashStore.getState().flashPlanet(42)
    const { unmount } = render(<HomeworldCandidateAttentionController markers={[]} />)
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).not.toBeNull()

    unmount()
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).toBeNull()
  })

  it('auto-clears flash after HOMEWORLD_CANDIDATE_FLASH_MS', () => {
    render(<HomeworldCandidateAttentionController markers={[]} />)

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(7)
    })
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).not.toBeNull()

    act(() => {
      vi.advanceTimersByTime(HOMEWORLD_CANDIDATE_FLASH_MS)
    })
    expect(useHomeworldCandidateFlashStore.getState().flashTarget).toBeNull()
  })

  it('keeps flash active when target changes before unmount', () => {
    render(<HomeworldCandidateAttentionController markers={[]} />)

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(1)
      useHomeworldCandidateFlashStore.getState().flashPlanet(2)
    })

    expect(useHomeworldCandidateFlashStore.getState().flashTarget?.planetId).toBe(2)
  })

  it('pans when markers become available after the flash token was set', () => {
    const { rerender } = render(
      <HomeworldCandidateAttentionController markers={[]} />
    )

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(42)
    })
    expect(setViewport).not.toHaveBeenCalled()

    rerender(<HomeworldCandidateAttentionController markers={offScreenMarkers} />)

    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('pans when domNode becomes available after the flash token was set', () => {
    mockDomNode = null
    const { rerender } = render(
      <HomeworldCandidateAttentionController markers={offScreenMarkers} />
    )

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(42)
    })
    expect(setViewport).not.toHaveBeenCalled()

    mockDomNode = mockPane
    rerender(<HomeworldCandidateAttentionController markers={offScreenMarkers} />)

    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('pans only once per flash token after markers are available', () => {
    const { rerender } = render(
      <HomeworldCandidateAttentionController markers={[]} />
    )

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(42)
    })
    expect(setViewport).not.toHaveBeenCalled()

    rerender(<HomeworldCandidateAttentionController markers={offScreenMarkers} />)
    expect(setViewport).toHaveBeenCalledTimes(1)

    rerender(<HomeworldCandidateAttentionController markers={offScreenMarkers} />)
    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('pans only once per flash token after domNode is available', () => {
    const { rerender } = render(
      <HomeworldCandidateAttentionController markers={offScreenMarkers} />
    )

    act(() => {
      useHomeworldCandidateFlashStore.getState().flashPlanet(42)
    })
    expect(setViewport).toHaveBeenCalledTimes(1)

    rerender(<HomeworldCandidateAttentionController markers={offScreenMarkers} />)
    expect(setViewport).toHaveBeenCalledTimes(1)
  })
})
