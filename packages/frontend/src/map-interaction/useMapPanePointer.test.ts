import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useMapPanePointer } from './useMapPanePointer'

const pane = document.createElement('div')

vi.mock('@xyflow/react', () => ({
  useStore: (
    selector: (s: { domNode: HTMLElement | null }) => unknown
  ) => selector({ domNode: pane }),
}))

describe('useMapPanePointer', () => {
  beforeEach(() => {
    vi.spyOn(pane, 'addEventListener')
    vi.spyOn(pane, 'removeEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('registers pane listeners and advances hitEpoch on move', () => {
    const { result, unmount } = renderHook(() => useMapPanePointer())
    expect(result.current.clientPos).toBeNull()
    expect(result.current.hitEpoch).toBe(0)

    const onMove = vi.mocked(pane.addEventListener).mock.calls.find(
      ([type]) => type === 'mousemove'
    )?.[1] as (e: MouseEvent) => void

    act(() => {
      onMove({ clientX: 3, clientY: 4 } as MouseEvent)
    })
    expect(result.current.clientPos).toEqual({ x: 3, y: 4 })
    expect(result.current.hitEpoch).toBe(1)

    act(() => {
      onMove({ clientX: 5, clientY: 6 } as MouseEvent)
    })
    expect(result.current.hitEpoch).toBe(2)

    const onLeave = vi.mocked(pane.addEventListener).mock.calls.find(
      ([type]) => type === 'mouseleave'
    )?.[1] as () => void
    act(() => {
      onLeave()
    })
    expect(result.current.clientPos).toBeNull()
    expect(result.current.hitEpoch).toBe(0)

    unmount()
    expect(pane.removeEventListener).toHaveBeenCalledWith(
      'mousemove',
      expect.any(Function)
    )
  })
})
