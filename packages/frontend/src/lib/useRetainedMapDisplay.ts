import { useLayoutEffect, useRef } from 'react'
import type { CombinedMapData } from '../api/bff'
import {
  deriveMapShellView,
  hasDisplayableMapData,
  shouldRetainMapDuringLoad,
  type MapShellView,
} from './mapDisplayRetention'

export type MapDisplayRetentionKey = {
  gameId: string
  perspective: number
}

export type UseRetainedMapDisplayInput = {
  combined: CombinedMapData | null | undefined
  gameId: string | null
  perspective: number | null
  viewMode: 'tabular' | 'map'
  turnDataReady: boolean
  turnEnsurePending: boolean
  mapPending: boolean
  mapHasError: boolean
  mapHasAnyData: boolean
}

export type UseRetainedMapDisplayResult = {
  displayMapData: CombinedMapData | null
  mapShellView: MapShellView
}

function mapDisplayRetentionKey(
  gameId: string | null,
  perspective: number | null
): MapDisplayRetentionKey | null {
  if (gameId == null || perspective == null) {
    return null
  }
  return { gameId, perspective }
}

function retentionKeysEqual(
  a: MapDisplayRetentionKey | null,
  b: MapDisplayRetentionKey | null
): boolean {
  return a?.gameId === b?.gameId && a?.perspective === b?.perspective
}

/**
 * Retains the last displayable combined map while map queries reload.
 * Clears synchronously when game id or perspective changes; retains across turn steps.
 */
export function useRetainedMapDisplay({
  combined,
  gameId,
  perspective,
  viewMode,
  turnDataReady,
  turnEnsurePending,
  mapPending,
  mapHasError,
  mapHasAnyData,
}: UseRetainedMapDisplayInput): UseRetainedMapDisplayResult {
  const retainedMapDataRef = useRef<CombinedMapData | null>(null)
  const retentionKeyRef = useRef<MapDisplayRetentionKey | null>(null)

  const currentKey = mapDisplayRetentionKey(gameId, perspective)
  const retentionKeyMatches = retentionKeysEqual(currentKey, retentionKeyRef.current)
  const retainedForCurrentKey = retentionKeyMatches
    ? retainedMapDataRef.current
    : null

  // useLayoutEffect (not useEffect) so ref updates run before paint, avoiding a flash of
  // another viewpoint's retained map when gameId or perspective changes.
  useLayoutEffect(() => {
    const key = mapDisplayRetentionKey(gameId, perspective)
    if (!retentionKeysEqual(key, retentionKeyRef.current)) {
      retainedMapDataRef.current = null
      retentionKeyRef.current = key
    }
    if (combined != null && hasDisplayableMapData(combined)) {
      retainedMapDataRef.current = combined
    }
  }, [gameId, perspective, combined])

  const showingLiveCombined =
    combined != null && hasDisplayableMapData(combined)
  const displayMapData: CombinedMapData | null = showingLiveCombined
    ? combined
    : retainedForCurrentKey
  const retainDuringLoad = shouldRetainMapDuringLoad(
    viewMode,
    showingLiveCombined ? null : retainedForCurrentKey
  )
  const hasAnalyticScope = gameId != null && perspective != null
  const mapShellView = deriveMapShellView({
    viewMode,
    displayMapData,
    retainDuringLoad,
    hasAnalyticScope,
    turnDataReady,
    turnEnsurePending,
    mapPending,
    mapHasError,
    mapHasAnyData,
  })

  return { displayMapData, mapShellView }
}
