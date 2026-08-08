import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
  isDiplomacyColorThreshold,
  type DiplomacyColorThreshold,
} from '../lib/diplomacyTier'
import {
  buildPlayerColorPaintSnapshot,
  DEFAULT_FAMILY_BASE_COLOR,
  DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
  defaultPlayerColorPaintSnapshotInputs,
  isPlayerColorMode,
  playerColorOverrideStorageKey,
  resolvePlayerColor,
  setPlayerColorResolutionPort,
  type PlayerColorMode,
  type PlayerColorOverrides,
  type PlayerColorPaintSnapshot,
  type PlayerColorPaintSnapshotInputs,
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
  /** Immutable paint snapshot; rebuilt when knobs or shell context change. */
  paintSnapshot: PlayerColorPaintSnapshot
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
}

function inboundRelationMapsEqual(
  a: ReadonlyMap<number, number>,
  b: ReadonlyMap<number, number>
): boolean {
  if (a === b) return true
  if (a.size !== b.size) return false
  for (const [playerId, relation] of a) {
    if (b.get(playerId) !== relation) return false
  }
  return true
}

function rosterPlayerIdsEqual(a: readonly number[], b: readonly number[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

function paintContextEquals(
  state: {
    viewpointPlayerId: number | null
    inboundRelationFromByPlayerId: ReadonlyMap<number, number>
    rosterPlayerIds: readonly number[]
  },
  ctx: {
    viewpointPlayerId: number | null
    inboundRelationFromByPlayerId: ReadonlyMap<number, number>
    rosterPlayerIds: readonly number[]
  }
): boolean {
  return (
    state.viewpointPlayerId === ctx.viewpointPlayerId &&
    inboundRelationMapsEqual(
      state.inboundRelationFromByPlayerId,
      ctx.inboundRelationFromByPlayerId
    ) &&
    rosterPlayerIdsEqual(state.rosterPlayerIds, ctx.rosterPlayerIds)
  )
}

function snapshotInputsFromState(
  state: PlayerColorsPersisted & {
    viewpointPlayerId: number | null
    inboundRelationFromByPlayerId: ReadonlyMap<number, number>
    rosterPlayerIds: readonly number[]
  }
): PlayerColorPaintSnapshotInputs {
  return {
    mode: state.mode,
    overrides: state.overrides,
    diplomacyThreshold: state.diplomacyThreshold,
    familyBaseColor: state.familyBaseColor,
    outOfCircleBaseColor: state.outOfCircleBaseColor,
    viewpointPlayerId: state.viewpointPlayerId,
    inboundRelationFromByPlayerId: state.inboundRelationFromByPlayerId,
    rosterPlayerIds: state.rosterPlayerIds,
  }
}

function withRebuiltSnapshot(
  state: PlayerColorsPersisted & {
    viewpointPlayerId: number | null
    inboundRelationFromByPlayerId: ReadonlyMap<number, number>
    rosterPlayerIds: readonly number[]
  },
  patch: Partial<PlayerColorsPersisted> & {
    viewpointPlayerId?: number | null
    inboundRelationFromByPlayerId?: ReadonlyMap<number, number>
    rosterPlayerIds?: readonly number[]
  }
): typeof patch & { paintSnapshot: PlayerColorPaintSnapshot } {
  const next = { ...state, ...patch }
  return {
    ...patch,
    paintSnapshot: buildPlayerColorPaintSnapshot(snapshotInputsFromState(next)),
  }
}

const initialSnapshotInputs = defaultPlayerColorPaintSnapshotInputs()

export const usePlayerColorsStore = create<PlayerColorsState>()(
  persist(
    (set, get) => ({
      overrides: {},
      mode: 'per_player',
      diplomacyThreshold: DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
      familyBaseColor: DEFAULT_FAMILY_BASE_COLOR,
      outOfCircleBaseColor: DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
      viewpointPlayerId: null,
      inboundRelationFromByPlayerId: EMPTY_INBOUND,
      rosterPlayerIds: EMPTY_ROSTER,
      paintSnapshot: buildPlayerColorPaintSnapshot(initialSnapshotInputs),
      setPlayerColorOverride: (playerId, color) =>
        set((state) => {
          const key = playerColorOverrideStorageKey(playerId)
          if (color == null || color.length === 0) {
            const rest = { ...state.overrides }
            delete rest[key]
            return withRebuiltSnapshot(state, { overrides: rest })
          }
          return withRebuiltSnapshot(state, {
            overrides: {
              ...state.overrides,
              [key]: color,
            },
          })
        }),
      setPlayerColorMode: (mode) => set((state) => withRebuiltSnapshot(state, { mode })),
      setDiplomacyThreshold: (diplomacyThreshold) =>
        set((state) => withRebuiltSnapshot(state, { diplomacyThreshold })),
      setFamilyBaseColor: (familyBaseColor) =>
        set((state) => withRebuiltSnapshot(state, { familyBaseColor })),
      setOutOfCircleBaseColor: (outOfCircleBaseColor) =>
        set((state) => withRebuiltSnapshot(state, { outOfCircleBaseColor })),
      setPaintContext: (ctx) => {
        if (paintContextEquals(get(), ctx)) return
        set((state) =>
          withRebuiltSnapshot(state, {
            viewpointPlayerId: ctx.viewpointPlayerId,
            inboundRelationFromByPlayerId: ctx.inboundRelationFromByPlayerId,
            rosterPlayerIds: ctx.rosterPlayerIds,
          })
        )
      },
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
          typeof p.mode === 'string' && isPlayerColorMode(p.mode) ? p.mode : current.mode
        const diplomacyThreshold =
          typeof p.diplomacyThreshold === 'number' &&
          isDiplomacyColorThreshold(p.diplomacyThreshold)
            ? p.diplomacyThreshold
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
        const merged = {
          ...current,
          overrides,
          mode,
          diplomacyThreshold,
          familyBaseColor,
          outOfCircleBaseColor,
        }
        return {
          ...merged,
          paintSnapshot: buildPlayerColorPaintSnapshot(snapshotInputsFromState(merged)),
        }
      },
    }
  )
)

/**
 * Bind zustand paint snapshot into the shared {@link colorForPlayerId} port.
 * Settings (or another always-mounted shell module) must import this module so
 * the port is installed and persisted knobs rehydrate.
 */
export function installPlayerColorsStorePort(): void {
  setPlayerColorResolutionPort({
    getSnapshot: () => usePlayerColorsStore.getState().paintSnapshot,
  })
}

installPlayerColorsStorePort()

/**
 * Reactive player color for map/table paint. Subscribes to the paint snapshot
 * so Settings and shell context updates re-render.
 */
export function usePlayerColor(playerId: number): string {
  const snapshot = usePlayerColorsStore((state) => state.paintSnapshot)
  return resolvePlayerColor(playerId, snapshot)
}

/** Clear shell paint context (no viewpoint / relations / roster). */
export function clearPlayerColorPaintContext(): void {
  usePlayerColorsStore.getState().setPaintContext({
    viewpointPlayerId: null,
    inboundRelationFromByPlayerId: EMPTY_INBOUND,
    rosterPlayerIds: EMPTY_ROSTER,
  })
}

/** Test helper: reset knobs + shell context and rebuild the paint snapshot. */
export function resetPlayerColorsStoreState(
  patch: Partial<PlayerColorPaintSnapshotInputs> = {}
): void {
  const inputs: PlayerColorPaintSnapshotInputs = {
    ...defaultPlayerColorPaintSnapshotInputs(),
    ...patch,
  }
  usePlayerColorsStore.setState({
    ...inputs,
    paintSnapshot: buildPlayerColorPaintSnapshot(inputs),
  })
}
