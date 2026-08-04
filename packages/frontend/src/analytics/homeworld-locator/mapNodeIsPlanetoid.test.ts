import { describe, expect, it } from 'vitest'
import type { MapNode } from '../../api/bff'
import { mapNodeIsPlanetoid, shouldOpenHomeworldPlanetMenu } from './mapNodeIsPlanetoid'

function mapNode(debrisdisk?: number): MapNode {
  return {
    id: 'base:p44',
    label: 'p44',
    x: 5,
    y: 5,
    planet: debrisdisk === undefined ? { id: 44 } : { id: 44, debrisdisk },
  }
}

describe('mapNodeIsPlanetoid', () => {
  it('is false for traditional planets (debrisdisk 0 or absent)', () => {
    expect(mapNodeIsPlanetoid(mapNode(0))).toBe(false)
    expect(mapNodeIsPlanetoid(mapNode())).toBe(false)
    expect(mapNodeIsPlanetoid({ id: 'base:p1', label: 'p1', x: 0, y: 0 })).toBe(false)
  })

  it('is true only when debrisdisk is exactly 1', () => {
    expect(mapNodeIsPlanetoid(mapNode(1))).toBe(true)
    expect(mapNodeIsPlanetoid(mapNode(37))).toBe(false)
  })
})

describe('shouldOpenHomeworldPlanetMenu', () => {
  it('allows traditional planet hits', () => {
    expect(shouldOpenHomeworldPlanetMenu(mapNode(0))).toBe(true)
    expect(shouldOpenHomeworldPlanetMenu(mapNode())).toBe(true)
    expect(shouldOpenHomeworldPlanetMenu(undefined)).toBe(true)
  })

  it('skips planetoids so sector hit-test can run', () => {
    expect(shouldOpenHomeworldPlanetMenu(mapNode(1))).toBe(false)
  })
})
