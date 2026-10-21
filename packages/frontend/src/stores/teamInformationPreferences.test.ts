import { beforeEach, describe, expect, it } from 'vitest'
import {
  byTeamForGame,
  hiddenPlayerIdsForGame,
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
      hiddenPlayerIdsByGameId: {},
    })
  })

  it('defaults owned planets only off and every league team visible', () => {
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(false)
    expect(state.hiddenLeagueTeamIds).toEqual([])
    expect(state.hiddenPlayerIdsByGameId).toEqual({})
    expect(byTeamForGame(state.byTeamByGameId, '628580')).toBe(false)
    expect(byTeamForGame(state.byTeamByGameId, null)).toBe(false)
    expect(hiddenPlayerIdsForGame(state.hiddenPlayerIdsByGameId, null)).toEqual([])
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
    expect(state.hiddenPlayerIdsByGameId).toEqual({})
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
    expect(state.hiddenPlayerIdsByGameId).toEqual({})
  })

  it('hides players for one game and leaves other games visible', () => {
    const store = useTeamInformationPreferencesStore.getState()
    store.setPlayerTerritoryVisible('111', 9, false)
    store.setPlayerTerritoryVisible('111', 7, false)
    store.setPlayerTerritoryVisible('222', 3, false)
    store.setPlayerTerritoryVisible('', 1, false)
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.hiddenPlayerIdsByGameId).toEqual({ '111': [7, 9], '222': [3] })
    expect(hiddenPlayerIdsForGame(state.hiddenPlayerIdsByGameId, '333')).toEqual([])
    const raw = localStorage.getItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    expect(raw).toContain('"111":[7,9]')
    expect(raw).toContain('"222":[3]')
    store.setPlayerTerritoryVisible('111', 7, true)
    expect(useTeamInformationPreferencesStore.getState().hiddenPlayerIdsByGameId).toEqual({
      '111': [9],
      '222': [3],
    })
    useTeamInformationPreferencesStore.getState().setPlayerTerritoryVisible('111', 9, true)
    expect(useTeamInformationPreferencesStore.getState().hiddenPlayerIdsByGameId).toEqual({
      '222': [3],
    })
  })

  it('rehydrates a blob with no player-hide field as every player visible', async () => {
    localStorage.setItem(
      TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        state: {
          ownedPlanetsOnly: true,
          hiddenLeagueTeamIds: [4],
          byTeamByGameId: { '111': true },
        },
        version: 3,
      })
    )
    await useTeamInformationPreferencesStore.persist.rehydrate()
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.ownedPlanetsOnly).toBe(true)
    expect(state.hiddenLeagueTeamIds).toEqual([4])
    expect(state.byTeamByGameId).toEqual({ '111': true })
    expect(state.hiddenPlayerIdsByGameId).toEqual({})
    expect(hiddenPlayerIdsForGame(state.hiddenPlayerIdsByGameId, '111')).toEqual([])
  })

  it('rehydrates hidden players for one game and drops empty or invalid ids', async () => {
    localStorage.setItem(
      TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        state: {
          ownedPlanetsOnly: false,
          hiddenLeagueTeamIds: [],
          byTeamByGameId: {},
          hiddenPlayerIdsByGameId: { '111': [0, -1, 1.5, 7], '222': [], '': [4] },
        },
        version: 4,
      })
    )
    await useTeamInformationPreferencesStore.persist.rehydrate()
    const state = useTeamInformationPreferencesStore.getState()
    expect(state.hiddenPlayerIdsByGameId).toEqual({ '111': [7] })
    expect(hiddenPlayerIdsForGame(state.hiddenPlayerIdsByGameId, '222')).toEqual([])
    expect(hiddenPlayerIdsForGame(state.hiddenPlayerIdsByGameId, null)).toEqual([])
  })
})
