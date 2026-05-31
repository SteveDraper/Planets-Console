import type { CombinedMapData } from '../api/bff'

export type MapShellPhase = 'full-loading' | 'retained' | 'ready' | 'error'

export type DeriveMapShellPhaseInput = {
  viewMode: 'tabular' | 'map'
  displayMapData: CombinedMapData | null
  retainDuringLoad: boolean
  turnDataReady: boolean
  turnEnsurePending: boolean
  mapPending: boolean
  mapHasError: boolean
  mapHasAnyData: boolean
}

/** Pure retention predicates; cross-turn ref retention lives in useRetainedMapDisplay. */

export function hasDisplayableMapData(data: CombinedMapData | null | undefined): boolean {
  return (data?.nodes.length ?? 0) > 0
}

/** Keep the map pane mounted (preserving React Flow viewport) while turn or map data reloads. */
export function shouldRetainMapDuringLoad(
  viewMode: 'tabular' | 'map',
  retainedMapData: CombinedMapData | null
): boolean {
  return viewMode === 'map' && hasDisplayableMapData(retainedMapData)
}

/** Single map-shell phase for MainArea loading, retention, and error UI. */
export function deriveMapShellPhase({
  viewMode,
  displayMapData,
  retainDuringLoad,
  turnDataReady,
  turnEnsurePending,
  mapPending,
  mapHasError,
  mapHasAnyData,
}: DeriveMapShellPhaseInput): MapShellPhase {
  if (retainDuringLoad) {
    return 'retained'
  }

  if (!turnDataReady && turnEnsurePending) {
    return 'full-loading'
  }

  if (viewMode !== 'map') {
    return displayMapData != null ? 'ready' : 'full-loading'
  }

  if (mapHasError && !mapHasAnyData) {
    return 'error'
  }

  if (displayMapData == null || (!mapHasAnyData && mapPending)) {
    return 'full-loading'
  }

  return 'ready'
}
