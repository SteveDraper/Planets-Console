import { create } from 'zustand'
import type { PerspectiveRow } from '../lib/gameInfoShell'

/** Snapshot from the last successful game-info refresh (turn cap and player order). */
export type GameInfoShellContext = {
  turn: number | null
  perspectives: PerspectiveRow[]
  /** When false, only the login-matched perspective may be selected in the shell. */
  isGameFinished: boolean
  /** `game.name` / `settings.name` from last refresh; drives sector display labels. */
  sectorDisplayName: string | null
}

type ShellState = {
  selectedGameId: string | null
  gameInfoContext: GameInfoShellContext | null
  /** Viewed turn in [1, gameInfoContext.turn] when known. */
  selectedTurn: number | null
  /** When set, overrides login-based default for the viewpoint control. */
  perspectiveOverrideName: string | null
  /** Last game id used for turn/perspective reset heuristics on refresh. */
  lastShellGameId: string | null
  setSelectedTurn: (turn: number | null) => void
  setPerspectiveOverrideName: (name: string | null) => void
  resetPerspectiveOverride: () => void
  /** Apply game-info refresh success: updates context, turn, and override rules. */
  applyGameInfoRefresh: (gameId: string, ctx: GameInfoShellContext) => void
}

export const useShellStore = create<ShellState>((set, get) => ({
  selectedGameId: null,
  gameInfoContext: null,
  selectedTurn: null,
  perspectiveOverrideName: null,
  lastShellGameId: null,
  setSelectedTurn: (turn) => set({ selectedTurn: turn }),
  setPerspectiveOverrideName: (name) => set({ perspectiveOverrideName: name }),
  resetPerspectiveOverride: () => set({ perspectiveOverrideName: null }),
  applyGameInfoRefresh: (gameId, ctx) => {
    const prevGameId = get().lastShellGameId
    const latestTurn = ctx.turn

    if (prevGameId !== gameId) {
      set({ perspectiveOverrideName: null })
    } else {
      const names = new Set(ctx.perspectives.map((p) => p.name))
      set((s) => ({
        perspectiveOverrideName:
          s.perspectiveOverrideName != null && names.has(s.perspectiveOverrideName)
            ? s.perspectiveOverrideName
            : null,
      }))
    }

    let nextTurn: number | null
    if (latestTurn == null || !Number.isFinite(latestTurn) || latestTurn < 1) {
      nextTurn = null
    } else if (prevGameId !== gameId) {
      nextTurn = Math.floor(latestTurn)
    } else {
      const t = get().selectedTurn
      nextTurn =
        t == null ? Math.floor(latestTurn) : Math.min(Math.max(1, t), Math.floor(latestTurn))
    }

    set({
      selectedGameId: gameId,
      gameInfoContext: ctx,
      selectedTurn: nextTurn,
      lastShellGameId: gameId,
    })
  },
}))
