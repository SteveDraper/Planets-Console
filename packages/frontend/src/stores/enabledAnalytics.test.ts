import { beforeEach, describe, expect, it } from 'vitest'
import {
  ENABLED_ANALYTICS_STORAGE_KEY,
  useEnabledAnalyticsStore,
} from '../stores/enabledAnalytics'

describe('useEnabledAnalyticsStore', () => {
  beforeEach(() => {
    localStorage.removeItem(ENABLED_ANALYTICS_STORAGE_KEY)
    useEnabledAnalyticsStore.setState({ enabledIds: [] })
  })

  it('defaults to no enabled analytics', () => {
    expect(useEnabledAnalyticsStore.getState().enabledIds).toEqual([])
    expect(useEnabledAnalyticsStore.getState().isEnabled('scores')).toBe(false)
  })

  it('toggles analytic ids in memory', () => {
    const { toggleEnabled, isEnabled } = useEnabledAnalyticsStore.getState()
    toggleEnabled('stellar-cartography')
    expect(isEnabled('stellar-cartography')).toBe(true)
    toggleEnabled('stellar-cartography')
    expect(isEnabled('stellar-cartography')).toBe(false)
  })

  it('persists enabled ids to localStorage', () => {
    useEnabledAnalyticsStore.getState().setEnabled('connections', true)
    useEnabledAnalyticsStore.getState().setEnabled('stellar-cartography', true)
    const raw = localStorage.getItem(ENABLED_ANALYTICS_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('stellar-cartography')
    expect(raw).toContain('connections')
  })
})
