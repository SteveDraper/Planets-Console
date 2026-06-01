import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import { MAP_SHELL_MAP_LOADING_MESSAGE } from './mapDisplayRetention'
import {
  defaultMapIds,
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

const retentionDefaults = {
  mapIds: defaultMapIds,
  mapError: null,
}

describe('useRetainedMapDisplay', () => {
  it('returns showing-map when combined is displayable', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({
        combined: sampleMap,
        ...defaultRetentionScope,
        ...retentionDefaults,
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
        mapIds,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapIds: readonly string[]
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          mapIds,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
          mapError: null,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapIds: defaultMapIds,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultRetentionScope,
      mapIds: defaultMapIds,
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
        mapIds,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapIds: readonly string[]
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          mapIds,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
          mapError: null,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapIds: defaultMapIds,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultRetentionScope,
      mapIds: defaultMapIds,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.mapShellView).toEqual(showingMap(sampleMap))

    rerender({
      combined: turnTwoMap,
      ...defaultRetentionScope,
      mapIds: defaultMapIds,
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
        mapIds,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapIds: readonly string[]
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          mapIds,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
          mapError: null,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapIds: defaultMapIds,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: otherGameMap,
      gameId: 'g2',
      perspective: 1,
      mapIds: defaultMapIds,
      mapPending: false,
      mapHasAnyData: true,
    })
    expect(result.current.mapShellView).toEqual(showingMap(otherGameMap))

    rerender({
      combined: emptyCombined,
      gameId: 'g2',
      perspective: 1,
      mapIds: defaultMapIds,
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
        mapIds,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapIds: readonly string[]
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          mapIds,
          ...initialMapLoad,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapIds: defaultMapIds,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      gameId: 'g2',
      perspective: 1,
      mapIds: defaultMapIds,
    })

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
        mapIds,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapIds: readonly string[]
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          mapIds,
          ...initialMapLoad,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultRetentionScope,
          mapIds: defaultMapIds,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      gameId: 'g1',
      perspective: 2,
      mapIds: defaultMapIds,
    })

    expect(result.current.mapShellView).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })

  it('clears retention when fetched map analytic ids change', () => {
    const cartographyMapIds: readonly string[] = [
      'base-map',
      'connections',
      'stellar-cartography',
    ]

    const { result, rerender } = renderHook(
      ({
        combined,
        mapIds,
      }: {
        combined: CombinedMapData | null
        mapIds: readonly string[]
      }) =>
        useRetainedMapDisplay({
          combined,
          ...defaultRetentionScope,
          mapIds,
          ...initialMapLoad,
        }),
      {
        initialProps: {
          combined: sampleMap,
          mapIds: cartographyMapIds,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      mapIds: defaultMapIds,
    })

    expect(result.current.mapShellView).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })
})
