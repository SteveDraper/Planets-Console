import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { MAP_ZOOM_MAX, MAP_ZOOM_MIN } from '../../lib/utils'
import { useCenteredViewportZoom } from './mapZoomKeyboardShortcuts'

const setViewport = vi.fn()
const getViewport = vi.fn(() => ({ x: 0, y: 0, zoom: 1 }))
const storeApi = {
  getState: () => ({
    domNode: {
      getBoundingClientRect: () => ({ width: 100, height: 100 }),
    },
  }),
}

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({ getViewport, setViewport }),
  useStoreApi: () => storeApi,
}))

describe('useCenteredViewportZoom', () => {
  beforeEach(() => {
    setViewport.mockClear()
    getViewport.mockClear()
  })

  it('clamps zoom to MAP_ZOOM_MIN and MAP_ZOOM_MAX', () => {
    const onMapZoomChange = vi.fn()
    const { result } = renderHook(() => useCenteredViewportZoom(onMapZoomChange))

    act(() => {
      result.current(0.01)
    })
    expect(setViewport).toHaveBeenCalledWith(expect.objectContaining({ zoom: MAP_ZOOM_MIN }))
    expect(onMapZoomChange).toHaveBeenCalledWith(MAP_ZOOM_MIN)

    act(() => {
      result.current(999)
    })
    expect(setViewport).toHaveBeenLastCalledWith(expect.objectContaining({ zoom: MAP_ZOOM_MAX }))
    expect(onMapZoomChange).toHaveBeenLastCalledWith(MAP_ZOOM_MAX)
  })
})
