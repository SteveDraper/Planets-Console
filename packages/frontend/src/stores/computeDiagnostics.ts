import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'

export type ClientStreamLifecycle = {
  /** Analytic / stream identity (e.g. ``fleet``, ``scores``); part of ``connectionKey``. */
  streamId: string
  connectionKey: string
  generation: number
  lastEventAt: string | null
  lastEventType: string | null
  lastConnectResult: string | null
}

/** Lightweight freeze control signal; independent of the Compute-tab snapshot. */
export type ComputeFreezeStatus = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
}

export type ComputeDiagnosticsSnapshot = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
  poolQueue: Record<string, unknown>[]
  inFlight: Record<string, unknown>[]
  dagNodes: Record<string, unknown>[]
  readyQueue: Record<string, unknown>[]
  nextSingleStep: {
    target: Record<string, unknown> | null
    disabledReason: string | null
  }
  completionHistory: Record<string, unknown>[]
  serverStreams: Record<string, unknown>[]
}

/**
 * A stream row refreshed with the same event type within this window keeps its
 * previous timestamp. Busy streams emit many same-type events (scoreboard
 * solutions, ledger writes); recording each one re-renders every subscriber.
 */
export const CLIENT_STREAM_REFRESH_THROTTLE_MS = 250

/** Whether ``entry`` only refreshes ``existing``'s timestamp within the throttle window. */
function isThrottledRefresh(existing: ClientStreamLifecycle, entry: ClientStreamLifecycle): boolean {
  if (
    existing.generation !== entry.generation ||
    existing.lastEventType !== entry.lastEventType ||
    existing.lastConnectResult !== entry.lastConnectResult ||
    existing.lastEventAt == null ||
    entry.lastEventAt == null
  ) {
    return false
  }
  const elapsedMs = Date.parse(entry.lastEventAt) - Date.parse(existing.lastEventAt)
  return elapsedMs >= 0 && elapsedMs < CLIENT_STREAM_REFRESH_THROTTLE_MS
}

type ComputeDiagnosticsState = {
  enabled: boolean
  /** Freeze hold signal fetched on shell change / app load when diagnostics are enabled. */
  freezeStatus: ComputeFreezeStatus | null
  /** Heavy observer snapshot; written only from the Compute tab. */
  snapshot: ComputeDiagnosticsSnapshot | null
  clientStreams: ClientStreamLifecycle[]
  setEnabled: (enabled: boolean) => void
  setFreezeStatus: (status: ComputeFreezeStatus | null) => void
  setSnapshot: (snapshot: ComputeDiagnosticsSnapshot | null) => void
  upsertClientStream: (entry: ClientStreamLifecycle) => void
  clearClientStreams: () => void
}

export const useComputeDiagnosticsStore = create<ComputeDiagnosticsState>()((set) => ({
  enabled: false,
  freezeStatus: null,
  snapshot: null,
  clientStreams: [],
  setEnabled: (enabled) =>
    set((state) => {
      if (enabled === state.enabled) {
        return state
      }
      return enabled
        ? { enabled: true, freezeStatus: null }
        : { enabled: false, freezeStatus: null }
    }),
  setFreezeStatus: (freezeStatus) => set({ freezeStatus }),
  setSnapshot: (snapshot) => set({ snapshot }),
  upsertClientStream: (entry) =>
    set((state) => {
      const existing = state.clientStreams.find(
        (candidate) => candidate.connectionKey === entry.connectionKey
      )
      if (existing != null && isThrottledRefresh(existing, entry)) {
        return state
      }
      const next = state.clientStreams.filter(
        (existing) => existing.connectionKey !== entry.connectionKey
      )
      next.push(entry)
      return { clientStreams: next }
    }),
  clearClientStreams: () => set({ clientStreams: [] }),
}))
