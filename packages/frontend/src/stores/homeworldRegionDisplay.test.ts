import { beforeEach, describe, expect, it } from 'vitest'
import { defaultHomeworldRegionDisplayMode } from '../analytics/homeworld-locator/homeworldRegionDisplayMode'
import {
  HOMEWORLD_REGION_DISPLAY_STORAGE_KEY,
  useHomeworldRegionDisplayStore,
} from './homeworldRegionDisplay'

describe('homeworldRegionDisplay store', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_DISPLAY_STORAGE_KEY)
    useHomeworldRegionDisplayStore.setState({
      regionDisplayMode: defaultHomeworldRegionDisplayMode(),
    })
  })

  it('defaults to un-pinned', () => {
    expect(useHomeworldRegionDisplayStore.getState().regionDisplayMode).toBe('un-pinned')
  })

  it('updates display mode', () => {
    useHomeworldRegionDisplayStore.getState().setRegionDisplayMode('all')
    expect(useHomeworldRegionDisplayStore.getState().regionDisplayMode).toBe('all')
    useHomeworldRegionDisplayStore.getState().setRegionDisplayMode('off')
    expect(useHomeworldRegionDisplayStore.getState().regionDisplayMode).toBe('off')
  })

  it('persists display mode to localStorage', () => {
    useHomeworldRegionDisplayStore.getState().setRegionDisplayMode('pinned')
    const raw = localStorage.getItem(HOMEWORLD_REGION_DISPLAY_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('pinned')
  })

  it('ignores invalid mode values', () => {
    useHomeworldRegionDisplayStore.getState().setRegionDisplayMode('pinned')
    useHomeworldRegionDisplayStore
      .getState()
      .setRegionDisplayMode('always' as 'off')
    expect(useHomeworldRegionDisplayStore.getState().regionDisplayMode).toBe('pinned')
  })
})
