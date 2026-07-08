import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { StellarCartographySettingsGates } from '../analytics/stellar-cartography/layers'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import type { PerspectiveRow } from '../lib/gameInfoShell'

const shellPersistStorage = createLocalStorageOrMemoryStateStorage()

export const SHELL_STORAGE_KEY = 'planets-console-shell'
const SHELL_PERSIST_VERSION = 2

export type ShellViewMode = 'tabular' | 'map'

/** Snapshot from the last successful game-info refresh (turn cap and player order). */
export type GameInfoShellContext = {
  turn: number | null
  perspectives: PerspectiveRow[]
  /** When false, only the login-matched perspective may be selected in the shell. */
  isGameFinished: boolean
  /** `game.name` / `settings.name` from last refresh; drives sector display labels. */
  sectorDisplayName: string | null
  /** NuHost settings gates for Stellar Cartography layer checkboxes. */
  stellarCartographyGates: StellarCartographySettingsGates
}

type ShellState = {
  selectedGameId: string | null
  gameInfoContext: GameInfoShellContext | null
  /** Viewed turn; may exceed gameInfoContext.turn for future prediction. */
  selectedTurn: number | null
  /** When set, overrides login-based default for the viewpoint control (1-based slot; 0 spectator). */
  perspectiveOverrideOrdinal: number | null
  /** Last game id used for turn/perspective reset heuristics on refresh. */
  lastShellGameId: string | null
  /** Game loaded from storage without login; turn ensure may skip credentials. */
  storageOnlyLoad: boolean
  /** Perspective slots with stored turn data for the current storage-only session. */
  storageAvailablePerspectives: number[] | null
  viewMode: ShellViewMode
  setSelectedTurn: (turn: number | null) => void
  setPerspectiveOverrideOrdinal: (ordinal: number | null) => void
  resetPerspectiveOverride: () => void
  setViewMode: (mode: ShellViewMode) => void
  setStorageAvailablePerspectives: (perspectives: number[] | null) => void
  clearStorageOnlyLoad: () => void
  /** Apply game-info refresh success: updates context, turn, and override rules. */
  applyGameInfoRefresh: (
    gameId: string,
    ctx: GameInfoShellContext,
    options?: ApplyGameInfoRefreshOptions
  ) => void
}

export type ApplyGameInfoRefreshOptions = {
  perspectiveOverrideOrdinal?: number | null
  storageOnlyLoad?: boolean
  storageAvailablePerspectives?: number[] | null
  /** Caps initial/clamped selected turn (host pseudo-view on in-progress games). */
  selectableTurnMax?: number | null
}

export const useShellStore = create<ShellState>()(
  persist(
    (set, get) => ({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      lastShellGameId: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
      viewMode: 'map',
      setSelectedTurn: (turn) => set({ selectedTurn: turn }),
      setPerspectiveOverrideOrdinal: (ordinal) => set({ perspectiveOverrideOrdinal: ordinal }),
      resetPerspectiveOverride: () => set({ perspectiveOverrideOrdinal: null }),
      setViewMode: (viewMode) => set({ viewMode }),
      setStorageAvailablePerspectives: (perspectives) =>
        set({ storageAvailablePerspectives: perspectives }),
      clearStorageOnlyLoad: () =>
        set({ storageOnlyLoad: false, storageAvailablePerspectives: null }),
      applyGameInfoRefresh: (gameId, ctx, options) => {
        const prevGameId = get().lastShellGameId
        const latestTurn = ctx.turn
        const overrideFromOptions = options?.perspectiveOverrideOrdinal

        if (prevGameId !== gameId) {
          set({ perspectiveOverrideOrdinal: overrideFromOptions ?? null })
        } else if (overrideFromOptions !== undefined) {
          set({ perspectiveOverrideOrdinal: overrideFromOptions })
        } else {
          const ordinals = new Set(ctx.perspectives.map((p) => p.ordinal))
          set((s) => ({
            perspectiveOverrideOrdinal:
              s.perspectiveOverrideOrdinal != null &&
              ordinals.has(s.perspectiveOverrideOrdinal)
                ? s.perspectiveOverrideOrdinal
                : null,
          }))
        }

        const rawCap =
          latestTurn == null || !Number.isFinite(latestTurn) || latestTurn < 1
            ? null
            : Math.floor(latestTurn)
        const optionCap = options?.selectableTurnMax
        const turnCap =
          rawCap == null
            ? null
            : optionCap != null && Number.isFinite(optionCap)
              ? Math.min(rawCap, Math.floor(optionCap))
              : rawCap

        let nextTurn: number | null
        if (turnCap == null || turnCap < 1) {
          nextTurn = null
        } else if (prevGameId !== gameId) {
          nextTurn = turnCap
        } else {
          const t = get().selectedTurn
          if (t == null) {
            nextTurn = turnCap
          } else if (t > turnCap) {
            nextTurn = t
          } else {
            nextTurn = Math.min(Math.max(1, t), turnCap)
          }
        }

        const storageOnlyLoad = options?.storageOnlyLoad ?? false

        set({
          selectedGameId: gameId,
          gameInfoContext: ctx,
          selectedTurn: nextTurn,
          lastShellGameId: gameId,
          storageOnlyLoad,
          storageAvailablePerspectives: storageOnlyLoad
            ? (options?.storageAvailablePerspectives ?? null)
            : null,
        })
      },
    }),
    {
      name: SHELL_STORAGE_KEY,
      version: SHELL_PERSIST_VERSION,
      storage: createJSONStorage(() => shellPersistStorage),
      migrate: (persisted) => {
        const state = (persisted as { state?: Record<string, unknown> })?.state ?? {}
        const { perspectiveOverrideName: _legacy, ...rest } = state
        return {
          ...(persisted as object),
          state: {
            ...rest,
            perspectiveOverrideOrdinal: null,
          },
        }
      },
      partialize: (state) => ({
        selectedGameId: state.selectedGameId,
        selectedTurn: state.selectedTurn,
        perspectiveOverrideOrdinal: state.perspectiveOverrideOrdinal,
        lastShellGameId: state.lastShellGameId,
        viewMode: state.viewMode,
      }),
    }
  )
)
