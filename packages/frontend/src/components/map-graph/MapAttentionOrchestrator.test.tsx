import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAP_ATTENTION_PULSE_MS } from '../../lib/mapAttention'
import {
  requestMapAttention,
  useMapAttentionRequestStore,
} from '../../stores/mapAttentionRequest'
import { MapAttentionOrchestrator } from './MapAttentionOrchestrator'

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

describe('MapAttentionOrchestrator', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useMapAttentionRequestStore.setState({ pending: null })
    mockDomNode = mockPane
    setViewport.mockClear()
    getViewport.mockClear()
    getViewport.mockReturnValue({ x: 0, y: 0, zoom: 1 })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('clears attention bus on unmount', () => {
    requestMapAttention({
      kind: 'homeworld-planet',
      planetId: 42,
      pan: 'if-offscreen',
    })
    const { unmount } = render(<MapAttentionOrchestrator homeworldMarkers={[]} />)
    expect(useMapAttentionRequestStore.getState().pending).not.toBeNull()

    unmount()
    expect(useMapAttentionRequestStore.getState().pending).toBeNull()
  })

  it('auto-clears attention after MAP_ATTENTION_PULSE_MS', () => {
    render(<MapAttentionOrchestrator homeworldMarkers={[]} />)

    act(() => {
      requestMapAttention({
        kind: 'homeworld-planet',
        planetId: 7,
        pan: 'if-offscreen',
      })
    })
    expect(useMapAttentionRequestStore.getState().pending).not.toBeNull()

    act(() => {
      vi.advanceTimersByTime(MAP_ATTENTION_PULSE_MS)
    })
    expect(useMapAttentionRequestStore.getState().pending).toBeNull()
  })

  it('pans when homeworld markers become available after the request', () => {
    const { rerender } = render(<MapAttentionOrchestrator homeworldMarkers={[]} />)

    act(() => {
      requestMapAttention({
        kind: 'homeworld-planet',
        planetId: 42,
        pan: 'if-offscreen',
      })
    })
    expect(setViewport).not.toHaveBeenCalled()

    rerender(<MapAttentionOrchestrator homeworldMarkers={offScreenMarkers} />)

    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('pans when domNode becomes available after the request', () => {
    mockDomNode = null
    const { rerender } = render(
      <MapAttentionOrchestrator homeworldMarkers={offScreenMarkers} />
    )

    act(() => {
      requestMapAttention({
        kind: 'homeworld-planet',
        planetId: 42,
        pan: 'if-offscreen',
      })
    })
    expect(setViewport).not.toHaveBeenCalled()

    mockDomNode = mockPane
    rerender(<MapAttentionOrchestrator homeworldMarkers={offScreenMarkers} />)

    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('pans only once per attention token', () => {
    const { rerender } = render(<MapAttentionOrchestrator homeworldMarkers={[]} />)

    act(() => {
      requestMapAttention({
        kind: 'homeworld-planet',
        planetId: 42,
        pan: 'if-offscreen',
      })
    })
    rerender(<MapAttentionOrchestrator homeworldMarkers={offScreenMarkers} />)
    expect(setViewport).toHaveBeenCalledTimes(1)

    rerender(<MapAttentionOrchestrator homeworldMarkers={offScreenMarkers} />)
    expect(setViewport).toHaveBeenCalledTimes(1)
  })

  it('always pans for wormhole-cell attention when the pane is ready', () => {
    render(<MapAttentionOrchestrator homeworldMarkers={[]} />)

    act(() => {
      requestMapAttention({
        kind: 'wormhole-cell',
        mapX: 100,
        mapY: 200,
        pan: 'always',
      })
    })

    expect(setViewport).toHaveBeenCalledTimes(1)
  })
})
