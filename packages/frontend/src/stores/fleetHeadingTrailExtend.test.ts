import { beforeEach, describe, expect, it } from 'vitest'
import {
  FLEET_HEADING_TRAIL_EXTEND_STORAGE_KEY,
  useFleetHeadingTrailExtendStore,
} from './fleetHeadingTrailExtend'

describe('useFleetHeadingTrailExtendStore', () => {
  beforeEach(() => {
    localStorage.removeItem(FLEET_HEADING_TRAIL_EXTEND_STORAGE_KEY)
    useFleetHeadingTrailExtendStore.setState({ extendTurns: 0 })
  })

  it('defaults to current-turn only (0)', () => {
    expect(useFleetHeadingTrailExtendStore.getState().extendTurns).toBe(0)
  })

  it('clamps and persists extend turns', () => {
    useFleetHeadingTrailExtendStore.getState().setExtendTurns(3)
    expect(useFleetHeadingTrailExtendStore.getState().extendTurns).toBe(3)
    const raw = localStorage.getItem(FLEET_HEADING_TRAIL_EXTEND_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"extendTurns":3')

    useFleetHeadingTrailExtendStore.getState().setExtendTurns(99)
    expect(useFleetHeadingTrailExtendStore.getState().extendTurns).toBe(5)
    useFleetHeadingTrailExtendStore.getState().setExtendTurns(-2)
    expect(useFleetHeadingTrailExtendStore.getState().extendTurns).toBe(0)
  })
})
