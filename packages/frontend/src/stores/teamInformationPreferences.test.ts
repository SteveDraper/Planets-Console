import { beforeEach, describe, expect, it } from 'vitest'
import {
  byTeamForGame,
  TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
  useTeamInformationPreferencesStore,
} from './teamInformationPreferences'

describe('teamInformationPreferences store', () => {
  beforeEach(() => {
    localStorage.removeItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    useTeamInformationPreferencesStore.setState({
      ownedPlanetsOnly: false,
      hiddenLeagueTeamIds: [],
      byTeamByGameId: {},
    })
  })

  it('defaults owned planets only off and every league team visible', () => {
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(false)
    expect(state.hiddenLeagueTeamIds).toEqual([])
    expect(byTeamForGame(state.byTeamByGameId, '628580')).toBe(false)
    expect(byTeamForGame(state.byTeamByGameId, null)).toBe(false)
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
    expect(state.byTeamByGameId).toEqual({})
  })

  it('stores by team for one game and leaves other games off', () => {
    const store = useTeamInformationPreferencesStore.getState()
    store.setByTeamForGame('111', true)
    store.setByTeamForGame('222', true)
    store.setByTeamForGame('111', false)
    const state = useTeamInformationPreferencesStore.getState()
    expect(byTeamForGame(state.byTeamByGameId, '111')).toBe(false)
    expect(byTeamForGame(state.byTeamByGameId, '222')).toBe(true)
    expect(byTeamForGame(state.byTeamByGameId, '333')).toBe(false)
    const raw = localStorage.getItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    expect(raw).toContain('"222":true')
    expect(raw).not.toContain('"111"')
  })

  it('rehydrates a pre-change blob as by team off for every game', async () => {
    localStorage.setItem(
      TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        state: { ownedPlanetsOnly: true, hiddenLeagueTeamIds: [4] },
        version: 2,
      })
    )
    await useTeamInformationPreferencesStore.persist.rehydrate()
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(true)
    expect(state.hiddenLeagueTeamIds).toEqual([4])
    expect(state.byTeamByGameId).toEqual({})
  })
})
