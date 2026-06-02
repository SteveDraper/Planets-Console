import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'

export type ScoresPlayerInferenceDiagnostics = {
  playerId: number
  racePlayer: string
  status: string
  summary: string
  turn: number
  constraints?: Record<string, unknown>
  actionCatalog?: Record<string, unknown>
  solver?: Record<string, unknown>
  diagnostics: Record<string, unknown>
}

export type ScoresAnalyticDiagnostics = {
  scope: AnalyticShellScope
  capturedAt: string
  includeBuildInference: boolean
  players: ScoresPlayerInferenceDiagnostics[]
}

type AnalyticDiagnosticsState = {
  scores: ScoresAnalyticDiagnostics | null
  setScoresDiagnostics: (snapshot: ScoresAnalyticDiagnostics | null) => void
}

export const useAnalyticDiagnosticsStore = create<AnalyticDiagnosticsState>()((set) => ({
  scores: null,
  setScoresDiagnostics: (snapshot) => set({ scores: snapshot }),
}))
