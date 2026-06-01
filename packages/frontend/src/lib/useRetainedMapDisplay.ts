import { useLayoutEffect, useRef } from 'react'
import type { CombinedMapData } from '../api/bff'
import {
  deriveMapShellView,
  hasDisplayableMapData,
  type MapFrame,
  type MapShellView,
} from './mapDisplayRetention'

export type MapDisplayRetentionKey = {
  gameId: string
  perspective: number
  mapIdsKey: string
}

export type UseRetainedMapDisplayInput = {
  combined: CombinedMapData | null | undefined
  gameId: string | null
  perspective: number | null
  mapIds: readonly string[]
  turnDataReady: boolean
  turnEnsurePending: boolean
  mapPending: boolean
  mapHasError: boolean
  mapHasAnyData: boolean
  mapError: unknown
}

export type UseRetainedMapDisplayResult = {
  mapShellView: MapShellView
}

function mapIdsRetentionKey(mapIds: readonly string[]): string {
  return mapIds.join('\0')
}

function mapDisplayRetentionKey(
  gameId: string | null,
  perspective: number | null,
  mapIds: readonly string[]
): MapDisplayRetentionKey | null {
  if (gameId == null || perspective == null) {
    return null
  }
  return { gameId, perspective, mapIdsKey: mapIdsRetentionKey(mapIds) }
}

function retentionKeysEqual(
  a: MapDisplayRetentionKey | null,
  b: MapDisplayRetentionKey | null
): boolean {
  return (
    a?.gameId === b?.gameId &&
    a?.perspective === b?.perspective &&
    a?.mapIdsKey === b?.mapIdsKey
  )
}

function deriveMapFrame(
  liveCombined: CombinedMapData | null | undefined,
  retainedForCurrentKey: CombinedMapData | null
): MapFrame {
  if (liveCombined != null && hasDisplayableMapData(liveCombined)) {
    return { source: 'live', data: liveCombined }
  }
  if (retainedForCurrentKey != null && hasDisplayableMapData(retainedForCurrentKey)) {
    return { source: 'retained', data: retainedForCurrentKey }
  }
  return { source: 'none' }
}

/**
 * Retains the last displayable combined map while map queries reload.
 * Clears when game id, perspective, or fetched map analytic set changes; retains across turn steps.
 */
export function useRetainedMapDisplay({
  combined,
  gameId,
  perspective,
  mapIds,
  turnDataReady,
  turnEnsurePending,
  mapPending,
  mapHasError,
  mapHasAnyData,
  mapError,
}: UseRetainedMapDisplayInput): UseRetainedMapDisplayResult {
  const retainedMapDataRef = useRef<CombinedMapData | null>(null)
  const retentionKeyRef = useRef<MapDisplayRetentionKey | null>(null)

  const currentKey = mapDisplayRetentionKey(gameId, perspective, mapIds)
  const retentionKeyMatches = retentionKeysEqual(currentKey, retentionKeyRef.current)
  const retainedForCurrentKey = retentionKeyMatches
    ? retainedMapDataRef.current
    : null

  // useLayoutEffect (not useEffect) so ref updates run before paint, avoiding a flash of
  // another viewpoint's retained map when gameId or perspective changes.
  useLayoutEffect(() => {
    const key = mapDisplayRetentionKey(gameId, perspective, mapIds)
    if (!retentionKeysEqual(key, retentionKeyRef.current)) {
      retainedMapDataRef.current = null
      retentionKeyRef.current = key
    }
    if (combined != null && hasDisplayableMapData(combined)) {
      retainedMapDataRef.current = combined
    }
  }, [gameId, perspective, mapIds, combined])

  const frame = deriveMapFrame(combined, retainedForCurrentKey)
  const hasAnalyticScope = gameId != null && perspective != null
  const mapShellView = deriveMapShellView({
    frame,
    hasAnalyticScope,
    turnDataReady,
    turnEnsurePending,
    mapPending,
    mapHasError,
    mapHasAnyData,
    mapError,
  })

  return { mapShellView }
}
