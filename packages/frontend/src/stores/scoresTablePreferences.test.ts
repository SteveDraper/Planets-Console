import { beforeEach, describe, expect, it } from 'vitest'
import {
  SCORES_TABLE_PREFERENCES_STORAGE_KEY,
  useScoresTablePreferencesStore,
} from '../stores/scoresTablePreferences'

describe('useScoresTablePreferencesStore', () => {
  beforeEach(() => {
    localStorage.removeItem(SCORES_TABLE_PREFERENCES_STORAGE_KEY)
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: false },
    })
  })

  it('defaults include build inference to false', () => {
    expect(useScoresTablePreferencesStore.getState().scoresTableParams).toEqual({
      includeBuildInference: false,
    })
  })

  it('persists include build inference to localStorage', () => {
    useScoresTablePreferencesStore.getState().setScoresTableParams({
      includeBuildInference: true,
    })
    const raw = localStorage.getItem(SCORES_TABLE_PREFERENCES_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('includeBuildInference')
    expect(raw).toContain('true')
  })
})
