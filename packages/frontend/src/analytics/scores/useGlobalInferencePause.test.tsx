import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope, InferenceGlobalPauseStatus } from '../../api/bff'
import * as bff from '../../api/bff'
import { useGlobalInferencePause } from './useGlobalInferencePause'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

function pauseStatus(paused: boolean): InferenceGlobalPauseStatus {
  return {
    gameId: 628580,
    perspective: 1,
    turn: 111,
    paused,
    activeScope: { gameId: 628580, perspective: 1, turn: 111 },
    heldJobCount: 0,
    heldContinuationCount: 0,
    activeSessionCount: paused ? 2 : 1,
  }
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

  it('calls pauseGlobally REST without updating chrome state', async () => {
    const pauseGlobally = vi
      .spyOn(bff, 'pauseInferenceGlobally')
      .mockResolvedValue(pauseStatus(true))

    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    await act(async () => {
      await result.current.pauseGlobally()
    })

    await waitFor(() => {
      expect(pauseGlobally).toHaveBeenCalledWith(scope)
      expect(result.current.isGloballyPaused).toBe(false)
      expect(result.current.isPending).toBe(false)
    })
  })

  it('calls resumeGlobally REST without updating chrome state', async () => {
    const resumeGlobally = vi
      .spyOn(bff, 'resumeInferenceGlobally')
      .mockResolvedValue(pauseStatus(false))

    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    act(() => {
      result.current.syncPausedFromStream(true)
    })

    await act(async () => {
      await result.current.resumeGlobally()
    })

    await waitFor(() => {
      expect(resumeGlobally).toHaveBeenCalledWith(scope)
      expect(result.current.isGloballyPaused).toBe(true)
      expect(result.current.isPending).toBe(false)
    })
  })

  it('surfaces REST errors from pauseGlobally without changing pause state', async () => {
    vi.spyOn(bff, 'pauseInferenceGlobally').mockRejectedValue(new Error('no active stream'))

    const { result } = renderHook(() => useGlobalInferencePause(scope, true))

    await act(async () => {
      await result.current.pauseGlobally()
    })

    await waitFor(() => {
      expect(result.current.error).toBe('no active stream')
      expect(result.current.isGloballyPaused).toBe(false)
      expect(result.current.isPending).toBe(false)
    })
  })
})
