import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'
import type {
  FleetTorpInputStatus,
  InferenceStreamSolutionPayload,
} from '../api/inferenceStreamEventSchema'
import { analyticScopeKey } from '../lib/analyticScopeKey'

type AnalyticScopeRef = Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>

const SCOPE_LEVEL_PLAYER_KEY = '__scope__'

function scopePlayerKey(scopeKey: string, playerId: number | null | undefined): string {
  return `${scopeKey}:${playerId ?? SCOPE_LEVEL_PLAYER_KEY}`
}

function solutionFingerprint(solutions: InferenceStreamSolutionPayload[]): string {
  return JSON.stringify(solutions)
}

type ScoresInferenceRevisionState = {
  revisionsByScopeKey: Record<string, number>
  lastSolutionFingerprintByScopePlayer: Record<string, string>
  lastFleetTorpInputStatusByScopePlayer: Record<string, FleetTorpInputStatus>
  bumpRevision: (scope: AnalyticScopeRef) => void
  resetRevisions: () => void
  clearBumpMemoryForScope: (scope: AnalyticScopeRef) => void
  noteSolutionEvidenceChangeAndShouldBumpRevision: (
    scope: AnalyticScopeRef,
    playerId: number | null | undefined,
    solutions: InferenceStreamSolutionPayload[],
    fleetTorpInputStatus: FleetTorpInputStatus | null
  ) => boolean
}

export const useScoresInferenceRevisionStore = create<ScoresInferenceRevisionState>()((set, get) => ({
  revisionsByScopeKey: {},
  lastSolutionFingerprintByScopePlayer: {},
  lastFleetTorpInputStatusByScopePlayer: {},
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
    set({
      revisionsByScopeKey: {},
      lastSolutionFingerprintByScopePlayer: {},
      lastFleetTorpInputStatusByScopePlayer: {},
    })
  },
  clearBumpMemoryForScope: (scope) => {
    const scopeKey = analyticScopeKey(scope)
    const prefix = `${scopeKey}:`
    set((state) => {
      const withoutScopePlayerKeys = <T extends Record<string, unknown>>(record: T): T => {
        const next = { ...record }
        for (const key of Object.keys(next)) {
          if (key.startsWith(prefix)) {
            delete next[key]
          }
        }
        return next
      }
      return {
        lastSolutionFingerprintByScopePlayer: withoutScopePlayerKeys(
          state.lastSolutionFingerprintByScopePlayer
        ),
        lastFleetTorpInputStatusByScopePlayer: withoutScopePlayerKeys(
          state.lastFleetTorpInputStatusByScopePlayer
        ),
      }
    })
  },
  noteSolutionEvidenceChangeAndShouldBumpRevision: (
    scope,
    playerId,
    solutions,
    fleetTorpInputStatus
  ) => {
    const playerKey = scopePlayerKey(analyticScopeKey(scope), playerId)
    const fingerprint = solutionFingerprint(solutions)
    const previousFingerprint = get().lastSolutionFingerprintByScopePlayer[playerKey]
    const previousStatus = get().lastFleetTorpInputStatusByScopePlayer[playerKey] ?? null

    const solutionsChanged = previousFingerprint !== fingerprint
    const statusChanged =
      fleetTorpInputStatus != null && fleetTorpInputStatus !== previousStatus

    if (!solutionsChanged && !statusChanged) {
      return false
    }

    set((state) => ({
      lastSolutionFingerprintByScopePlayer: {
        ...state.lastSolutionFingerprintByScopePlayer,
        [playerKey]: fingerprint,
      },
      ...(fleetTorpInputStatus != null
        ? {
            lastFleetTorpInputStatusByScopePlayer: {
              ...state.lastFleetTorpInputStatusByScopePlayer,
              [playerKey]: fleetTorpInputStatus,
            },
          }
        : {}),
    }))
    return true
  },
}))

export function bumpScoresInferenceRevision(scope: AnalyticScopeRef): void {
  useScoresInferenceRevisionStore.getState().bumpRevision(scope)
}

export function clearBumpMemoryForScope(scope: AnalyticScopeRef): void {
  useScoresInferenceRevisionStore.getState().clearBumpMemoryForScope(scope)
}

export function noteSolutionEvidenceChangeAndShouldBumpRevision(
  scope: AnalyticScopeRef,
  playerId: number | null | undefined,
  solutions: InferenceStreamSolutionPayload[],
  fleetTorpInputStatus: FleetTorpInputStatus | null
): boolean {
  return useScoresInferenceRevisionStore
    .getState()
    .noteSolutionEvidenceChangeAndShouldBumpRevision(
      scope,
      playerId,
      solutions,
      fleetTorpInputStatus
    )
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
