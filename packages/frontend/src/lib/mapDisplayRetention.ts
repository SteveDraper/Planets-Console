import type { CombinedMapData } from '../api/bff'

export type MapShellPhase = 'full-loading' | 'retained' | 'ready' | 'error'

export const MAP_SHELL_TURN_LOADING_MESSAGE = 'Loading turn data…'
export const MAP_SHELL_MAP_LOADING_MESSAGE = 'Loading map…'

export type MapShellView =
  | { phase: 'inactive' }
  | { phase: 'full-loading'; loadingMessage: string }
  | { phase: 'retained'; displayMapData: CombinedMapData }
  | { phase: 'ready'; displayMapData: CombinedMapData }
  | { phase: 'error' }

export type DeriveMapShellViewInput = {
  viewMode: 'tabular' | 'map'
  displayMapData: CombinedMapData | null
  retainDuringLoad: boolean
  hasAnalyticScope: boolean
  turnDataReady: boolean
  turnEnsurePending: boolean
  mapPending: boolean
  mapHasError: boolean
  mapHasAnyData: boolean
}

/** @deprecated Prefer DeriveMapShellViewInput */
export type DeriveMapShellPhaseInput = Omit<DeriveMapShellViewInput, 'hasAnalyticScope'> & {
  hasAnalyticScope?: boolean
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

/** Unified map-shell view for MainArea loading, retention, and error UI. */
export function deriveMapShellView({
  viewMode,
  displayMapData,
  retainDuringLoad,
  hasAnalyticScope,
  turnDataReady,
  turnEnsurePending,
  mapPending,
  mapHasError,
  mapHasAnyData,
}: DeriveMapShellViewInput): MapShellView {
  if (retainDuringLoad && displayMapData != null) {
    return { phase: 'retained', displayMapData }
  }

  if (hasAnalyticScope && !turnDataReady && turnEnsurePending) {
    return { phase: 'full-loading', loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE }
  }

  if (viewMode !== 'map') {
    return { phase: 'inactive' }
  }

  if (mapHasError && !mapHasAnyData) {
    return { phase: 'error' }
  }

  if (displayMapData == null || (!mapHasAnyData && mapPending)) {
    return { phase: 'full-loading', loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE }
  }

  return { phase: 'ready', displayMapData }
}

/** Single map-shell phase; use deriveMapShellView when loading copy or displayMapData guarantees matter. */
export function deriveMapShellPhase(input: DeriveMapShellPhaseInput): MapShellPhase {
  const view = deriveMapShellView({
    ...input,
    hasAnalyticScope: input.hasAnalyticScope ?? true,
  })
  if (view.phase === 'inactive') {
    return input.displayMapData != null ? 'ready' : 'full-loading'
  }
  return view.phase
}
