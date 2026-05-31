import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import { MAP_SHELL_MAP_LOADING_MESSAGE } from './mapDisplayRetention'
import { useRetainedMapDisplay } from './useRetainedMapDisplay'

const sampleMap: CombinedMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

const turnTwoMap: CombinedMapData = {
  ...sampleMap,
  nodes: [{ id: 'base-map:1', label: 'A', x: 3, y: 4 }],
}

const emptyCombined: CombinedMapData = { ...sampleMap, nodes: [] }

const defaultScope = { gameId: 'g1', perspective: 1 }

const idleMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: false,
  mapHasError: false,
  mapHasAnyData: true,
}

const initialMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: true,
  mapHasError: false,
  mapHasAnyData: false,
}

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
        ...defaultScope,
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
          ...defaultScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultScope,
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
          ...defaultScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultScope,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.mapShellView).toEqual(showingMap(sampleMap))

    rerender({
      combined: turnTwoMap,
      ...defaultScope,
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
          ...defaultScope,
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
      { initialProps: { combined: sampleMap, ...defaultScope } }
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
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g1', perspective: 2 })

    expect(result.current.mapShellView).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })
})
