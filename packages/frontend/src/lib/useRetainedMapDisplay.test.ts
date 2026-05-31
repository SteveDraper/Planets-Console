import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import { MAP_SHELL_MAP_LOADING_MESSAGE } from './mapDisplayRetention'
import {
  defaultRetentionScope,
  emptyCombined,
  idleMapLoad,
  initialMapLoad,
  sampleMap,
  turnTwoMap,
} from './mapDisplayTestFixtures'
import { useRetainedMapDisplay } from './useRetainedMapDisplay'

function showingMap(
  displayMapData: CombinedMapData,
  showDeferredPending = false
) {
  return {
    phase: 'showing-map' as const,
    displayMapData,
    showDeferredPending,
  }
}

describe('useRetainedMapDisplay', () => {
  it('returns showing-map when combined is displayable', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({
        combined: sampleMap,
        ...defaultRetentionScope,
        ...idleMapLoad,
      })
    )
    expect(result.current.mapShellView).toEqual(showingMap(sampleMap))
  })

  it('retains prior map across empty combined within the same game and perspective', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultRetentionScope,
      mapPending: true,
      mapHasAnyData: false,
    })

    expect(result.current.mapShellView).toEqual(showingMap(sampleMap))
  })

  it('retains across turn step when game and perspective are unchanged', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultRetentionScope,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.mapShellView).toEqual(showingMap(sampleMap))

    rerender({
      combined: turnTwoMap,
      ...defaultRetentionScope,
      mapPending: false,
      mapHasAnyData: true,
    })
    expect(result.current.mapShellView).toEqual(showingMap(turnTwoMap))
  })

  it('retains only within the current game and perspective key', () => {
    const otherGameMap: CombinedMapData = {
      ...sampleMap,
      nodes: [{ id: 'base-map:99', label: 'Z', x: 9, y: 9 }],
    }

    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: otherGameMap,
      gameId: 'g2',
      perspective: 1,
      mapPending: false,
      mapHasAnyData: true,
    })
    expect(result.current.mapShellView).toEqual(showingMap(otherGameMap))

    rerender({
      combined: emptyCombined,
      gameId: 'g2',
      perspective: 1,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.mapShellView).toEqual(showingMap(otherGameMap))
  })

  it('clears retention after gameId changes', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          ...initialMapLoad,
        }),
      { initialProps: { combined: sampleMap, ...defaultRetentionScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g2', perspective: 1 })

    expect(result.current.mapShellView).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })

  it('clears retention after perspective changes', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          ...initialMapLoad,
        }),
      { initialProps: { combined: sampleMap, ...defaultRetentionScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g1', perspective: 2 })

    expect(result.current.mapShellView).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })
})
