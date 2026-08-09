import { describe, expect, it } from 'vitest'
import { debrisdiskValue, planetIsInDebrisDisk } from './debrisdisk'

describe('debrisdiskValue', () => {
  it('returns finite numbers as-is', () => {
    expect(debrisdiskValue(0)).toBe(0)
    expect(debrisdiskValue(1)).toBe(1)
    expect(debrisdiskValue(37)).toBe(37)
  })

  it('parses non-empty numeric strings', () => {
    expect(debrisdiskValue('0')).toBe(0)
    expect(debrisdiskValue('1')).toBe(1)
    expect(debrisdiskValue(' 37 ')).toBe(37)
  })

  it('returns null for missing or non-numeric values', () => {
    expect(debrisdiskValue(undefined)).toBeNull()
    expect(debrisdiskValue(null)).toBeNull()
    expect(debrisdiskValue('')).toBeNull()
    expect(debrisdiskValue('   ')).toBeNull()
    expect(debrisdiskValue('abc')).toBeNull()
    expect(debrisdiskValue(Number.NaN)).toBeNull()
    expect(debrisdiskValue(Number.POSITIVE_INFINITY)).toBeNull()
    expect(debrisdiskValue({})).toBeNull()
  })
})

describe('planetIsInDebrisDisk', () => {
  it('is false for traditional planets (0 or absent)', () => {
    expect(planetIsInDebrisDisk(0)).toBe(false)
    expect(planetIsInDebrisDisk('0')).toBe(false)
    expect(planetIsInDebrisDisk(undefined)).toBe(false)
    expect(planetIsInDebrisDisk(null)).toBe(false)
  })

  it('is true for any non-zero debrisdisk (planetoid or other)', () => {
    expect(planetIsInDebrisDisk(1)).toBe(true)
    expect(planetIsInDebrisDisk('1')).toBe(true)
    expect(planetIsInDebrisDisk(37)).toBe(true)
  })
})
