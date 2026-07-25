import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import {
  defaultVisibilityKindPreferences,
  isVisibilityRegionKind,
  type VisibilityKindPreferences,
  type VisibilityRegionKind,
} from '../analytics/visibility/kinds'

const visibilityPreferencesPersistStorage = createLocalStorageOrMemoryStateStorage()

export const VISIBILITY_PREFERENCES_STORAGE_KEY = 'planets-console-visibility-preferences'

const PERSIST_VERSION = 2

type VisibilityPreferencesState = {
  kinds: VisibilityKindPreferences
  isKindEnabled: (kind: VisibilityRegionKind) => boolean
  setKindEnabled: (kind: VisibilityRegionKind, enabled: boolean) => void
  setKindFillColor: (kind: VisibilityRegionKind, fillColor: string) => void
}

type VisibilityPreferencesPersisted = Pick<VisibilityPreferencesState, 'kinds'>

function migratePersistedState(
  persisted: unknown,
  _version: number
): VisibilityPreferencesPersisted {
  const raw = persisted as { kinds?: Partial<VisibilityKindPreferences> }
  const defaults = defaultVisibilityKindPreferences()
  const kinds = { ...defaults }
  if (raw.kinds != null) {
    for (const kind of Object.keys(defaults) as VisibilityRegionKind[]) {
      const entry = raw.kinds[kind]
      if (entry == null) continue
      kinds[kind] = {
        enabled: entry.enabled ?? defaults[kind].enabled,
        fillColor:
          typeof entry.fillColor === 'string' && entry.fillColor.length > 0
            ? entry.fillColor
            : defaults[kind].fillColor,
      }
    }
  }
  return { kinds }
}

export const useVisibilityPreferencesStore = create<VisibilityPreferencesState>()(
  persist(
    (set, get) => ({
      kinds: defaultVisibilityKindPreferences(),
      isKindEnabled: (kind) => get().kinds[kind]?.enabled ?? true,
      setKindEnabled: (kind, enabled) =>
        set((state) => ({
          kinds: {
            ...state.kinds,
            [kind]: { ...state.kinds[kind], enabled },
          },
        })),
      setKindFillColor: (kind, fillColor) => {
        if (!isVisibilityRegionKind(kind)) return
        set((state) => ({
          kinds: {
            ...state.kinds,
            [kind]: { ...state.kinds[kind], fillColor },
          },
        }))
      },
    }),
    {
      name: VISIBILITY_PREFERENCES_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => visibilityPreferencesPersistStorage),
      partialize: (state) => ({ kinds: state.kinds }),
      migrate: (persisted, version) => {
        if (version >= PERSIST_VERSION) {
          return migratePersistedState(persisted, version)
        }
        return migratePersistedState(persisted, version)
      },
    }
  )
)
