import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, renderHook } from '@testing-library/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  RegionOverlayHoverTooltip,
  useMapPaneClientPos,
  useRegionOverlayHoverLines,
} from './RegionOverlayHoverPanel'

const pane = document.createElement('div')
pane.getBoundingClientRect = () =>
  ({
    left: 10,
    top: 20,
    right: 110,
    bottom: 120,
    width: 100,
    height: 100,
    x: 10,
    y: 20,
    toJSON: () => ({}),
  }) as DOMRect

vi.mock('@xyflow/react', () => ({
  useStore: (
    selector: (s: {
      domNode: HTMLElement | null
      transform: [number, number, number]
    }) => unknown
  ) => selector({ domNode: pane, transform: [0, 0, 1] }),
}))

vi.mock('./geometry', () => ({
  clientToFlowPosition: (clientX: number, clientY: number) => ({
    x: clientX,
    y: clientY,
  }),
}))

vi.mock('../../lib/planetSpatialGrid', () => ({
  flowCenterToPlanet: (x: number, y: number) => ({ px: x, py: y }),
}))

vi.mock('../../lib/mapRegionOverlayHitTest', () => ({
  collectRegionOverlayHoverSummaries: () => ['region line'],
}))

const sampleOverlay: MapRegionOverlay = {
  kind: 'homeworld-sector',
  id: 's1',
  fillColor: '#fff',
  fillOpacity: 0.2,
  hoverSummary: 'pinned',
  geometry: { type: 'coverage', disks: [], patches: [] },
}

describe('useMapPaneClientPos', () => {
  beforeEach(() => {
    vi.spyOn(pane, 'addEventListener')
    vi.spyOn(pane, 'removeEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('registers a single mousemove/mouseleave pair on the pane', () => {
    const { unmount } = renderHook(() => useMapPaneClientPos())

    expect(pane.addEventListener).toHaveBeenCalledTimes(2)
    expect(pane.addEventListener).toHaveBeenCalledWith('mousemove', expect.any(Function))
    expect(pane.addEventListener).toHaveBeenCalledWith('mouseleave', expect.any(Function))

    unmount()
    expect(pane.removeEventListener).toHaveBeenCalledWith('mousemove', expect.any(Function))
    expect(pane.removeEventListener).toHaveBeenCalledWith('mouseleave', expect.any(Function))
  })

  it('updates clientPos from pane pointer events', () => {
    const { result } = renderHook(() => useMapPaneClientPos())
    expect(result.current.clientPos).toBeNull()

    const onMove = vi.mocked(pane.addEventListener).mock.calls.find(
      ([type]) => type === 'mousemove'
    )?.[1] as (e: MouseEvent) => void

    act(() => {
      onMove({ clientX: 42, clientY: 84 } as MouseEvent)
    })
    expect(result.current.clientPos).toEqual({ x: 42, y: 84 })

    const onLeave = vi.mocked(pane.addEventListener).mock.calls.find(
      ([type]) => type === 'mouseleave'
    )?.[1] as () => void
    act(() => {
      onLeave()
    })
    expect(result.current.clientPos).toBeNull()
  })
})

describe('useRegionOverlayHoverLines', () => {
  beforeEach(() => {
    vi.spyOn(pane, 'addEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shares one pointer source and suppresses lines when blocked by planet hover', () => {
    const { result, rerender } = renderHook(
      ({ blocked }: { blocked: boolean }) =>
        useRegionOverlayHoverLines([sampleOverlay], blocked),
      { initialProps: { blocked: false } }
    )

    expect(pane.addEventListener).toHaveBeenCalledTimes(2)

    const onMove = vi.mocked(pane.addEventListener).mock.calls.find(
      ([type]) => type === 'mousemove'
    )?.[1] as (e: MouseEvent) => void
    act(() => {
      onMove({ clientX: 50, clientY: 60 } as MouseEvent)
    })
    expect(result.current.clientPos).toEqual({ x: 50, y: 60 })
    expect(result.current.lines).toEqual(['region line'])

    rerender({ blocked: true })
    expect(result.current.clientPos).toEqual({ x: 50, y: 60 })
    expect(result.current.lines).toEqual([])
    // Rerender must not attach a second listener pair.
    expect(pane.addEventListener).toHaveBeenCalledTimes(2)
  })
})

describe('RegionOverlayHoverTooltip', () => {
  beforeEach(() => {
    vi.spyOn(pane, 'addEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('positions from shared clientPos without attaching pointer listeners', () => {
    const { container } = render(
      <RegionOverlayHoverTooltip
        lines={['pinned · 1 candidate']}
        clientPos={{ x: 30, y: 40 }}
      />
    )

    expect(pane.addEventListener).not.toHaveBeenCalled()
    const tip = container.firstElementChild as HTMLElement
    expect(tip.style.left).toBe('32px') // 30 - 10 + 12
    expect(tip.style.top).toBe('12px') // 40 - 20 - 8
    expect(tip.textContent).toBe('pinned · 1 candidate')
  })

  it('renders nothing when lines are empty (planet-hover suppression)', () => {
    const { container } = render(
      <RegionOverlayHoverTooltip lines={[]} clientPos={{ x: 30, y: 40 }} />
    )
    expect(container.firstChild).toBeNull()
  })
})
