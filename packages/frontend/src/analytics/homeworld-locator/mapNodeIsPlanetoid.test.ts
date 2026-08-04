import { describe, expect, it } from 'vitest'
import type { MapNode } from '../../api/bff'
import {
  mapNodeIsPlanetoid,
  shouldOpenHomeworldPlanetMenu,
  shouldSuppressHomeworldMenusForPlanetHit,
} from './mapNodeIsPlanetoid'

function mapNode(debrisdisk?: number | string): MapNode {
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
    expect(mapNodeIsPlanetoid(mapNode('1'))).toBe(true)
    expect(mapNodeIsPlanetoid(mapNode(37))).toBe(false)
  })
})

describe('shouldOpenHomeworldPlanetMenu', () => {
  it('allows traditional planet hits', () => {
    expect(shouldOpenHomeworldPlanetMenu(mapNode(0))).toBe(true)
    expect(shouldOpenHomeworldPlanetMenu(mapNode())).toBe(true)
  })

  it('fails closed when the map node is missing', () => {
    expect(shouldOpenHomeworldPlanetMenu(undefined)).toBe(false)
  })

  it('skips planetoids', () => {
    expect(shouldOpenHomeworldPlanetMenu(mapNode(1))).toBe(false)
  })
})

describe('shouldSuppressHomeworldMenusForPlanetHit', () => {
  it('suppresses only confirmed planetoid hits (no sector fall-through)', () => {
    expect(shouldSuppressHomeworldMenusForPlanetHit(mapNode(1))).toBe(true)
    expect(shouldSuppressHomeworldMenusForPlanetHit(mapNode(0))).toBe(false)
    expect(shouldSuppressHomeworldMenusForPlanetHit(undefined)).toBe(false)
  })

  it('suppresses planetoid hits shaped like base-map wire (e.g. game 680224 planet 25)', () => {
    const planet25: MapNode = {
      id: 'base-map:p25',
      label: 'p25',
      x: 100,
      y: 200,
      planet: { id: 25, name: 'Feringilitai - 9', debrisdisk: 1 },
    }
    expect(mapNodeIsPlanetoid(planet25)).toBe(true)
    expect(shouldSuppressHomeworldMenusForPlanetHit(planet25)).toBe(true)
    expect(shouldOpenHomeworldPlanetMenu(planet25)).toBe(false)
  })
})
