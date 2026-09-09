import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import {
  defaultMinefieldTypePreferences,
  type MinefieldTypePreferencesById,
} from '../analytics/minefields/minefieldPaint'
import {
  MINEFIELD_TYPE_IDS,
  type MinefieldPaintPolicy,
  type MinefieldTypeId,
} from '../analytics/minefields/types'

const persistStorage = createLocalStorageOrMemoryStateStorage()

export const MINEFIELDS_PREFERENCES_STORAGE_KEY = 'planets-console-minefields-preferences'

const PERSIST_VERSION = 1

type MinefieldsPreferencesState = {
  types: MinefieldTypePreferencesById
  isTypeEnabled: (typeId: MinefieldTypeId) => boolean
  setTypeEnabled: (typeId: MinefieldTypeId, enabled: boolean) => void
  setTypePolicy: (typeId: MinefieldTypeId, policy: MinefieldPaintPolicy) => void
  setStanceInColor: (typeId: MinefieldTypeId, color: string) => void
  setStanceOutColor: (typeId: MinefieldTypeId, color: string) => void
}

type MinefieldsPreferencesPersisted = Pick<MinefieldsPreferencesState, 'types'>

function migratePersistedState(persisted: unknown): MinefieldsPreferencesPersisted {
  const defaults = defaultMinefieldTypePreferences()
  const types = defaultMinefieldTypePreferences()
  const raw = persisted as { types?: Partial<MinefieldTypePreferencesById> }
  if (raw.types != null) {
    for (const typeId of MINEFIELD_TYPE_IDS) {
      const entry = raw.types[typeId]
      if (entry == null) continue
      types[typeId] = {
        enabled: entry.enabled ?? defaults[typeId].enabled,
        policy: entry.policy === 'stance' || entry.policy === 'owner' ? entry.policy : defaults[typeId].policy,
        stanceInColor:
          typeof entry.stanceInColor === 'string' && entry.stanceInColor.length > 0
            ? entry.stanceInColor
            : defaults[typeId].stanceInColor,
        stanceOutColor:
          typeof entry.stanceOutColor === 'string' && entry.stanceOutColor.length > 0
            ? entry.stanceOutColor
            : defaults[typeId].stanceOutColor,
      }
    }
  }
  return { types }
}

export const useMinefieldsPreferencesStore = create<MinefieldsPreferencesState>()(
  persist(
    (set, get) => ({
      types: defaultMinefieldTypePreferences(),
      isTypeEnabled: (typeId) => get().types[typeId]?.enabled ?? true,
      setTypeEnabled: (typeId, enabled) =>
        set((state) => ({
          types: {
            ...state.types,
            [typeId]: { ...state.types[typeId], enabled },
          },
        })),
      setTypePolicy: (typeId, policy) =>
        set((state) => ({
          types: {
            ...state.types,
            [typeId]: { ...state.types[typeId], policy },
          },
        })),
      setStanceInColor: (typeId, color) =>
        set((state) => ({
          types: {
            ...state.types,
            [typeId]: { ...state.types[typeId], stanceInColor: color },
          },
        })),
      setStanceOutColor: (typeId, color) =>
        set((state) => ({
          types: {
            ...state.types,
            [typeId]: { ...state.types[typeId], stanceOutColor: color },
          },
        })),
    }),
    {
      name: MINEFIELDS_PREFERENCES_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => persistStorage),
      partialize: (state) => ({ types: state.types }),
      migrate: (persisted) => migratePersistedState(persisted),
    }
  )
)
