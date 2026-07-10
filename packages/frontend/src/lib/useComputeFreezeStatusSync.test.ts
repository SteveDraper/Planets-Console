import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../api/bff'
import * as bffComputeDiagnostics from '../api/bffComputeDiagnostics'
import { useComputeDiagnosticsStore } from '../stores/computeDiagnostics'
import { useComputeFreezeStatusSync } from './useComputeFreezeStatusSync'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 8,
  perspective: 1,
}

describe('useComputeFreezeStatusSync', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: false,
      freezeStatus: null,
      snapshot: null,
      clientStreams: [],
    })
    vi.restoreAllMocks()
  })

  it('does not fetch when diagnostics are disabled', async () => {
    const fetchSpy = vi.spyOn(bffComputeDiagnostics, 'fetchComputeDiagnosticsFreezeStatus')
    renderHook(() => useComputeFreezeStatusSync(scope))
    await act(async () => {
      await Promise.resolve()
    })
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(useComputeDiagnosticsStore.getState().freezeStatus).toBeNull()
  })

  it('fetches freeze status on enable and stores it without a snapshot', async () => {
    const fetchSpy = vi
      .spyOn(bffComputeDiagnostics, 'fetchComputeDiagnosticsFreezeStatus')
      .mockResolvedValue({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [],
      })

    useComputeDiagnosticsStore.getState().setEnabled(true)
    renderHook(() => useComputeFreezeStatusSync(scope))

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(scope)
      expect(useComputeDiagnosticsStore.getState().freezeStatus).toEqual({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [],
      })
    })
    expect(useComputeDiagnosticsStore.getState().snapshot).toBeNull()
  })

  it('refetches on shell change and updates sticky allowlist reset', async () => {
    const fetchSpy = vi
      .spyOn(bffComputeDiagnostics, 'fetchComputeDiagnosticsFreezeStatus')
      .mockResolvedValueOnce({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [3, 7],
      })
      .mockResolvedValueOnce({
        shell: { gameId: '628580', turn: 9, perspective: 1 },
        freezeArmed: true,
        allowlistedPlayerIds: [],
      })

    useComputeDiagnosticsStore.getState().setEnabled(true)
    const { rerender } = renderHook(
      ({ shell }: { shell: AnalyticShellScope }) => useComputeFreezeStatusSync(shell),
      { initialProps: { shell: scope } }
    )

    await waitFor(() => {
      expect(useComputeDiagnosticsStore.getState().freezeStatus?.allowlistedPlayerIds).toEqual([
        3, 7,
      ])
    })

    rerender({ shell: { gameId: '628580', turn: 9, perspective: 1 } })

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2)
      expect(useComputeDiagnosticsStore.getState().freezeStatus).toEqual({
        shell: { gameId: '628580', turn: 9, perspective: 1 },
        freezeArmed: true,
        allowlistedPlayerIds: [],
      })
    })
  })

  it('rehydrates freeze armed and allowlist on same-shell remount (SPA refresh)', async () => {
    const fetchSpy = vi
      .spyOn(bffComputeDiagnostics, 'fetchComputeDiagnosticsFreezeStatus')
      .mockResolvedValue({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [11],
      })

    useComputeDiagnosticsStore.getState().setEnabled(true)
    const { unmount } = renderHook(() => useComputeFreezeStatusSync(scope))
    await waitFor(() => {
      expect(useComputeDiagnosticsStore.getState().freezeStatus?.allowlistedPlayerIds).toEqual([
        11,
      ])
    })
    unmount()

    // Simulate full remount after browser refresh: store may still be empty until sync.
    useComputeDiagnosticsStore.setState({ freezeStatus: null, snapshot: null })
    renderHook(() => useComputeFreezeStatusSync(scope))
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2)
      expect(useComputeDiagnosticsStore.getState().freezeStatus).toEqual({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [11],
      })
    })
  })
})
