import { beforeEach, describe, expect, it } from 'vitest'
import {
  useVisibilityPreferencesStore,
  VISIBILITY_PREFERENCES_STORAGE_KEY,
} from './visibilityPreferences'
import { defaultVisibilityKindPreferences } from '../analytics/visibility/kinds'

describe('visibilityPreferences store', () => {
  beforeEach(() => {
    localStorage.removeItem(VISIBILITY_PREFERENCES_STORAGE_KEY)
    useVisibilityPreferencesStore.setState({
      kinds: defaultVisibilityKindPreferences(),
    })
  })

    it('defaults all kinds on with distinct colors', () => {
    const kinds = useVisibilityPreferencesStore.getState().kinds
    expect(kinds['ship-scan'].enabled).toBe(true)
    expect(kinds['active-sensor-sweep'].enabled).toBe(true)
    expect(kinds['potential-sensor-sweep'].enabled).toBe(true)
    expect(kinds['active-minefield-detect'].enabled).toBe(true)
    expect(kinds['potential-minefield-detect'].enabled).toBe(true)
    const colors = new Set(Object.values(kinds).map((k) => k.fillColor))
    expect(colors.size).toBe(5)
  })

  it('persists kind toggles and colors', () => {
    useVisibilityPreferencesStore.getState().setKindEnabled('ship-scan', false)
    useVisibilityPreferencesStore.getState().setKindFillColor('active-sensor-sweep', '#abcdef')
    const raw = localStorage.getItem(VISIBILITY_PREFERENCES_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('ship-scan')
    expect(raw).toContain('#abcdef')
  })
})
