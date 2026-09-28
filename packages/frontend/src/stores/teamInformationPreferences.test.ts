import { beforeEach, describe, expect, it } from 'vitest'
import {
  TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
  useTeamInformationPreferencesStore,
} from './teamInformationPreferences'

describe('teamInformationPreferences store', () => {
  beforeEach(() => {
    localStorage.removeItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    useTeamInformationPreferencesStore.setState({ ownedPlanetsOnly: false })
  })

  it('defaults owned planets only off', () => {
    expect(useTeamInformationPreferencesStore.getState().ownedPlanetsOnly).toBe(false)
  })

  it('persists the checkbox to localStorage', () => {
    useTeamInformationPreferencesStore.getState().setOwnedPlanetsOnly(true)
    const raw = localStorage.getItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    expect(raw).toContain('"ownedPlanetsOnly":true')
  })
})
