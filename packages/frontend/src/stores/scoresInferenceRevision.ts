import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'
import type { FleetTorpInputStatus } from '../api/inferenceStreamEventSchema'
import { analyticScopeKey } from '../lib/analyticScopeKey'

type AnalyticScopeRef = Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>

type ScoresInferenceRevisionState = {
  revisionsByScopeKey: Record<string, number>
  lastFleetTorpInputStatusByScopeKey: Record<string, FleetTorpInputStatus>
  bumpRevision: (scope: AnalyticScopeRef) => void
  resetRevisions: () => void
  clearLastFleetTorpInputStatusForScope: (scope: AnalyticScopeRef) => void
  noteFleetTorpInputStatusChangeAndShouldBumpRevision: (
    scope: AnalyticScopeRef,
    status: FleetTorpInputStatus | null
  ) => boolean
}

export const useScoresInferenceRevisionStore = create<ScoresInferenceRevisionState>()((set, get) => ({
  revisionsByScopeKey: {},
  lastFleetTorpInputStatusByScopeKey: {},
  bumpRevision: (scope) => {
    const key = analyticScopeKey(scope)
    set((state) => ({
      revisionsByScopeKey: {
        ...state.revisionsByScopeKey,
        [key]: (state.revisionsByScopeKey[key] ?? 0) + 1,
      },
    }))
  },
  resetRevisions: () => {
    set({ revisionsByScopeKey: {}, lastFleetTorpInputStatusByScopeKey: {} })
  },
  clearLastFleetTorpInputStatusForScope: (scope) => {
    const key = analyticScopeKey(scope)
    set((state) => {
      if (!(key in state.lastFleetTorpInputStatusByScopeKey)) {
        return state
      }
      const { [key]: _removed, ...lastFleetTorpInputStatusByScopeKey } =
        state.lastFleetTorpInputStatusByScopeKey
      return { lastFleetTorpInputStatusByScopeKey }
    })
  },
  noteFleetTorpInputStatusChangeAndShouldBumpRevision: (scope, status) => {
    if (status == null) {
      return false
    }
    const key = analyticScopeKey(scope)
    const previousStatus = get().lastFleetTorpInputStatusByScopeKey[key] ?? null
    if (status === previousStatus) {
      return false
    }
    set((state) => ({
      lastFleetTorpInputStatusByScopeKey: {
        ...state.lastFleetTorpInputStatusByScopeKey,
        [key]: status,
      },
    }))
    return true
  },
}))

export function bumpScoresInferenceRevision(scope: AnalyticScopeRef): void {
  useScoresInferenceRevisionStore.getState().bumpRevision(scope)
}

export function clearLastFleetTorpInputStatusForScope(scope: AnalyticScopeRef): void {
  useScoresInferenceRevisionStore.getState().clearLastFleetTorpInputStatusForScope(scope)
}

export function noteFleetTorpInputStatusChangeAndShouldBumpRevision(
  scope: AnalyticScopeRef,
  status: FleetTorpInputStatus | null
): boolean {
  return useScoresInferenceRevisionStore
    .getState()
    .noteFleetTorpInputStatusChangeAndShouldBumpRevision(scope, status)
}

export function scoresInferenceRevisionForScope(scope: AnalyticScopeRef): number {
  const key = analyticScopeKey(scope)
  return useScoresInferenceRevisionStore.getState().revisionsByScopeKey[key] ?? 0
}

export function useScoresInferenceRevision(scope: AnalyticShellScope | null): number {
  const scopeKey = scope != null ? analyticScopeKey(scope) : null
  return useScoresInferenceRevisionStore((state) =>
    scopeKey != null ? (state.revisionsByScopeKey[scopeKey] ?? 0) : 0
  )
}
