import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import * as bff from '../../api/bff'
import { useGlobalInferencePause } from './useGlobalInferencePause'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

describe('useGlobalInferencePause', () => {
  it('does not fetch REST pause status on mount when enabled', () => {
    const fetchStatus = vi.spyOn(bff, 'fetchInferenceGlobalPauseStatus')

    renderHook(() => useGlobalInferencePause(scope, true))

    expect(fetchStatus).not.toHaveBeenCalled()
  })

  it('resets pause state when disabled', () => {
    const { result, rerender } = renderHook(
      ({ enabled }) => useGlobalInferencePause(scope, enabled),
      { initialProps: { enabled: true } }
    )

    act(() => {
      result.current.syncPausedFromStream(true)
    })
    expect(result.current.isGloballyPaused).toBe(true)

    rerender({ enabled: false })

    expect(result.current.isGloballyPaused).toBe(false)
  })

  it('syncs pause state from stream events', () => {
    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    act(() => {
      result.current.syncPausedFromStream(true)
    })
    expect(result.current.isGloballyPaused).toBe(true)

    act(() => {
      result.current.syncPausedFromStream(false)
    })
    expect(result.current.isGloballyPaused).toBe(false)
  })

  it('updates pause state from pauseGlobally REST action', async () => {
    vi.spyOn(bff, 'pauseInferenceGlobally').mockResolvedValue({ paused: true })

    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    await act(async () => {
      await result.current.pauseGlobally()
    })

    await waitFor(() => {
      expect(result.current.isGloballyPaused).toBe(true)
      expect(result.current.isPending).toBe(false)
    })
  })

  it('updates pause state from resumeGlobally REST action', async () => {
    vi.spyOn(bff, 'resumeInferenceGlobally').mockResolvedValue({ paused: false })

    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    act(() => {
      result.current.syncPausedFromStream(true)
    })

    await act(async () => {
      await result.current.resumeGlobally()
    })

    await waitFor(() => {
      expect(result.current.isGloballyPaused).toBe(false)
      expect(result.current.isPending).toBe(false)
    })
  })
})
