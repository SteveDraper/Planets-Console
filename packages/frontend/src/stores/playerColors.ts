import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
  isDiplomacyColorThreshold,
  type DiplomacyColorThreshold,
} from '../lib/diplomacyTier'
import {
  colorForPlayerId as resolvePlayerColor,
  DEFAULT_FAMILY_BASE_COLOR,
  DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
  playerColorOverrideStorageKey,
  setPlayerColorResolutionPort,
  type PlayerColorMode,
  type PlayerColorOverrides,
} from '../lib/playerColor'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const playerColorsPersistStorage = createLocalStorageOrMemoryStateStorage()

export const PLAYER_COLORS_STORAGE_KEY = 'planets-console-player-colors'

const EMPTY_INBOUND = new Map<number, number>()
const EMPTY_ROSTER: readonly number[] = []

type PlayerColorsPersisted = {
  overrides: PlayerColorOverrides
  mode: PlayerColorMode
  diplomacyThreshold: DiplomacyColorThreshold
  familyBaseColor: string
  outOfCircleBaseColor: string
}

type PlayerColorsState = PlayerColorsPersisted & {
  /** Shell paint context -- not persisted. */
  viewpointPlayerId: number | null
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>
  rosterPlayerIds: readonly number[]
  /** Bumps so ``usePlayerColor`` re-renders on any paint-affecting change. */
  paintRevision: number
  setPlayerColorOverride: (playerId: number, color: string | null) => void
  setPlayerColorMode: (mode: PlayerColorMode) => void
  setDiplomacyThreshold: (threshold: DiplomacyColorThreshold) => void
  setFamilyBaseColor: (color: string) => void
  setOutOfCircleBaseColor: (color: string) => void
  setPaintContext: (ctx: {
    viewpointPlayerId: number | null
    inboundRelationFromByPlayerId: ReadonlyMap<number, number>
    rosterPlayerIds: readonly number[]
  }) => void
  colorForPlayerId: (playerId: number) => string
}

function bumpRevision(state: PlayerColorsState): number {
  return state.paintRevision + 1
}

export const usePlayerColorsStore = create<PlayerColorsState>()(
  persist(
    (set) => ({
      overrides: {},
      mode: 'per_player',
      diplomacyThreshold: DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
      familyBaseColor: DEFAULT_FAMILY_BASE_COLOR,
      outOfCircleBaseColor: DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
      viewpointPlayerId: null,
      inboundRelationFromByPlayerId: EMPTY_INBOUND,
      rosterPlayerIds: EMPTY_ROSTER,
      paintRevision: 0,
      setPlayerColorOverride: (playerId, color) =>
        set((state) => {
          const key = playerColorOverrideStorageKey(playerId)
          if (color == null || color.length === 0) {
            const rest = { ...state.overrides }
            delete rest[key]
            return { overrides: rest, paintRevision: bumpRevision(state) }
          }
          return {
            overrides: {
              ...state.overrides,
              [key]: color,
            },
            paintRevision: bumpRevision(state),
          }
        }),
      setPlayerColorMode: (mode) =>
        set((state) => ({ mode, paintRevision: bumpRevision(state) })),
      setDiplomacyThreshold: (diplomacyThreshold) =>
        set((state) => ({ diplomacyThreshold, paintRevision: bumpRevision(state) })),
      setFamilyBaseColor: (familyBaseColor) =>
        set((state) => ({ familyBaseColor, paintRevision: bumpRevision(state) })),
      setOutOfCircleBaseColor: (outOfCircleBaseColor) =>
        set((state) => ({ outOfCircleBaseColor, paintRevision: bumpRevision(state) })),
      setPaintContext: ({
        viewpointPlayerId,
        inboundRelationFromByPlayerId,
        rosterPlayerIds,
      }) =>
        set((state) => ({
          viewpointPlayerId,
          inboundRelationFromByPlayerId,
          rosterPlayerIds,
          paintRevision: bumpRevision(state),
        })),
      colorForPlayerId: (playerId) => resolvePlayerColor(playerId),
    }),
    {
      name: PLAYER_COLORS_STORAGE_KEY,
      storage: createJSONStorage(() => playerColorsPersistStorage),
      partialize: (state) => ({
        overrides: state.overrides,
        mode: state.mode,
        diplomacyThreshold: state.diplomacyThreshold,
        familyBaseColor: state.familyBaseColor,
        outOfCircleBaseColor: state.outOfCircleBaseColor,
      }),
      merge: (persisted, current) => {
        const p =
          persisted != null && typeof persisted === 'object'
            ? (persisted as Partial<PlayerColorsPersisted>)
            : {}
        const mode: PlayerColorMode =
          p.mode === 'diplomacy_family' || p.mode === 'per_player' ? p.mode : current.mode
        const diplomacyThreshold = isDiplomacyColorThreshold(p.diplomacyThreshold as number)
          ? (p.diplomacyThreshold as DiplomacyColorThreshold)
          : current.diplomacyThreshold
        const familyBaseColor =
          typeof p.familyBaseColor === 'string' && p.familyBaseColor.length > 0
            ? p.familyBaseColor
            : current.familyBaseColor
        const outOfCircleBaseColor =
          typeof p.outOfCircleBaseColor === 'string' && p.outOfCircleBaseColor.length > 0
            ? p.outOfCircleBaseColor
            : current.outOfCircleBaseColor
        const overrides =
          p.overrides != null && typeof p.overrides === 'object' ? p.overrides : current.overrides
        return {
          ...current,
          overrides,
          mode,
          diplomacyThreshold,
          familyBaseColor,
          outOfCircleBaseColor,
        }
      },
    }
  )
)

/**
 * Bind zustand state into the shared {@link colorForPlayerId} resolution port.
 * Settings (or another always-mounted shell module) must import this module so
 * the port is installed and persisted knobs rehydrate.
 */
export function installPlayerColorsStorePort(): void {
  setPlayerColorResolutionPort({
    getMode: () => usePlayerColorsStore.getState().mode,
    getOverride: (playerId) =>
      usePlayerColorsStore.getState().overrides[playerColorOverrideStorageKey(playerId)],
    getDiplomacyThreshold: () => usePlayerColorsStore.getState().diplomacyThreshold,
    getFamilyBaseColor: () => usePlayerColorsStore.getState().familyBaseColor,
    getOutOfCircleBaseColor: () => usePlayerColorsStore.getState().outOfCircleBaseColor,
    getViewpointPlayerId: () => usePlayerColorsStore.getState().viewpointPlayerId,
    getInboundRelationFromByPlayerId: () =>
      usePlayerColorsStore.getState().inboundRelationFromByPlayerId,
    getRosterPlayerIds: () => usePlayerColorsStore.getState().rosterPlayerIds,
  })
}

installPlayerColorsStorePort()

/**
 * Reactive player color for map/table paint. Subscribes to paint-affecting
 * store changes so Settings and shell context updates re-render.
 */
export function usePlayerColor(playerId: number): string {
  usePlayerColorsStore((state) => state.paintRevision)
  return resolvePlayerColor(playerId)
}

/** Clear shell paint context (no viewpoint / relations / roster). */
export function clearPlayerColorPaintContext(): void {
  usePlayerColorsStore.getState().setPaintContext({
    viewpointPlayerId: null,
    inboundRelationFromByPlayerId: EMPTY_INBOUND,
    rosterPlayerIds: EMPTY_ROSTER,
  })
}
