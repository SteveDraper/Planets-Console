import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'

export type ClientStreamLifecycle = {
  connectionKey: string
  generation: number
  lastEventAt: string | null
  lastEventType: string | null
  lastConnectResult: string | null
}

export type ComputeDiagnosticsSnapshot = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
  poolQueue: Record<string, unknown>[]
  dagNodes: Record<string, unknown>[]
  readyQueue: Record<string, unknown>[]
  completionHistory: Record<string, unknown>[]
  serverStreams: Record<string, unknown>[]
  clientStreams: ClientStreamLifecycle[]
}

type ComputeDiagnosticsState = {
  enabled: boolean
  snapshot: ComputeDiagnosticsSnapshot | null
  clientStreams: ClientStreamLifecycle[]
  setEnabled: (enabled: boolean) => void
  setSnapshot: (snapshot: ComputeDiagnosticsSnapshot | null) => void
  upsertClientStream: (entry: ClientStreamLifecycle) => void
  clearClientStreams: () => void
}

export const useComputeDiagnosticsStore = create<ComputeDiagnosticsState>()((set) => ({
  enabled: false,
  snapshot: null,
  clientStreams: [],
  setEnabled: (enabled) => set({ enabled }),
  setSnapshot: (snapshot) => set({ snapshot }),
  upsertClientStream: (entry) =>
    set((state) => {
      const next = state.clientStreams.filter(
        (existing) => existing.connectionKey !== entry.connectionKey
      )
      next.push(entry)
      return { clientStreams: next }
    }),
  clearClientStreams: () => set({ clientStreams: [] }),
}))

export function filterPlayerIdsForComputeFreeze(
  scope: AnalyticShellScope | null,
  playerIds: number[]
): number[] {
  const snapshot = useComputeDiagnosticsStore.getState().snapshot
  if (scope == null || snapshot == null || !snapshot.freezeArmed) {
    return playerIds
  }
  if (
    snapshot.shell.gameId !== scope.gameId ||
    snapshot.shell.perspective !== scope.perspective ||
    snapshot.shell.turn !== scope.turn
  ) {
    return playerIds
  }
  const allowlisted = new Set(snapshot.allowlistedPlayerIds)
  return playerIds.filter((playerId) => allowlisted.has(playerId))
}
