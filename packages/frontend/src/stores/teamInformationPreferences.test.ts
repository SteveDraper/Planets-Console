import { beforeEach, describe, expect, it } from 'vitest'
import {
  TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
  useTeamInformationPreferencesStore,
} from './teamInformationPreferences'

describe('teamInformationPreferences store', () => {
  beforeEach(() => {
    localStorage.removeItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    useTeamInformationPreferencesStore.setState({
      ownedPlanetsOnly: false,
      hiddenLeagueTeamIds: [],
    })
  })

  it('defaults owned planets only off and every league team visible', () => {
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(false)
    expect(state.hiddenLeagueTeamIds).toEqual([])
  })

  it('persists the checkbox to localStorage', () => {
    useTeamInformationPreferencesStore.getState().setOwnedPlanetsOnly(true)
    const raw = localStorage.getItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    expect(raw).toContain('"ownedPlanetsOnly":true')
  })

  it('persists unchecked league team ids and clears them when rechecked', () => {
    const store = useTeamInformationPreferencesStore.getState()
    store.setLeagueTeamRegionVisible(9, false)
    store.setLeagueTeamRegionVisible(4, false)
    expect(useTeamInformationPreferencesStore.getState().hiddenLeagueTeamIds).toEqual([4, 9])
    const raw = localStorage.getItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    expect(raw).toContain('"hiddenLeagueTeamIds":[4,9]')
    useTeamInformationPreferencesStore.getState().setLeagueTeamRegionVisible(4, true)
    expect(useTeamInformationPreferencesStore.getState().hiddenLeagueTeamIds).toEqual([9])
  })

  it('rehydrates a v1 blob as all league teams visible', async () => {
    localStorage.setItem(
      TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      JSON.stringify({ state: { ownedPlanetsOnly: true }, version: 1 })
    )
    await useTeamInformationPreferencesStore.persist.rehydrate()
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(true)
    expect(state.hiddenLeagueTeamIds).toEqual([])
  })
})
