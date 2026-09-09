import { beforeEach, describe, expect, it } from 'vitest'
import {
  MINEFIELDS_PREFERENCES_STORAGE_KEY,
  useMinefieldsPreferencesStore,
} from './minefieldsPreferences'
import { defaultMinefieldTypePreferences } from '../analytics/minefields/minefieldPaint'

describe('minefieldsPreferences store', () => {
  beforeEach(() => {
    localStorage.removeItem(MINEFIELDS_PREFERENCES_STORAGE_KEY)
    useMinefieldsPreferencesStore.setState({
      types: defaultMinefieldTypePreferences(),
    })
  })

  it('defaults normal owner and web stance, both enabled', () => {
    const types = useMinefieldsPreferencesStore.getState().types
    expect(types.normal.enabled).toBe(true)
    expect(types.web.enabled).toBe(true)
    expect(types.normal.policy).toBe('owner')
    expect(types.web.policy).toBe('stance')
    expect(types.web.stanceInColor).toBe('#8480d4')
    expect(types.web.stanceOutColor).toBe('#a78bfa')
  })

  it('persists type enable, policy, and stance colors', () => {
    useMinefieldsPreferencesStore.getState().setTypeEnabled('normal', false)
    useMinefieldsPreferencesStore.getState().setTypePolicy('web', 'owner')
    useMinefieldsPreferencesStore.getState().setStanceInColor('normal', '#111111')
    const raw = localStorage.getItem(MINEFIELDS_PREFERENCES_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('normal')
    expect(raw).toContain('#111111')
    expect(raw).toContain('owner')
  })
})
