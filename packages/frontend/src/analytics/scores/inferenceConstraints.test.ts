import { describe, expect, it } from 'vitest'
import {
  formatSignedDelta,
  militaryChangeFromDelta2x,
  readInferenceConstraints,
  readMilitaryScoreArithmetic,
} from './inferenceConstraints'

describe('readInferenceConstraints', () => {
  it('reads constraint fields from diagnostics', () => {
    const constraints = readInferenceConstraints({
      constraints: {
        turn: 8,
        playerId: 3,
        militaryDelta2x: 50,
        warshipDelta: 1,
        freighterDelta: -2,
        requestedPriorityPointDelta: 10,
        priorityPointConstraintNote: 'PP diagnostic only',
        appliedEqualities: ['sum(scoreDelta2x * count) == 50'],
      },
    })
    expect(constraints?.turn).toBe(8)
    expect(constraints?.militaryDelta2x).toBe(50)
    expect(constraints?.priorityPointConstraintNote).toBe('PP diagnostic only')
    expect(constraints?.appliedEqualities).toHaveLength(1)
  })
})

describe('readMilitaryScoreArithmetic', () => {
  it('parses military score arithmetic payload', () => {
    const arithmetic = readMilitaryScoreArithmetic({
      observedMilitaryChange: 25,
      observedMilitaryDelta2x: 50,
      explainedMilitaryChange: 25,
      explainedMilitaryDelta2x: 50,
      matchesObserved: true,
      lineItems: [
        {
          actionId: 'defense',
          label: 'Defense post',
          count: 2,
          scoreDelta2xPerUnit: 22,
          militaryChangePerUnit: 11,
          scoreDelta2xSubtotal: 44,
          militaryChangeSubtotal: 22,
        },
      ],
    })
    expect(arithmetic?.matchesObserved).toBe(true)
    expect(arithmetic?.lineItems[0]?.militaryChangeSubtotal).toBe(22)
  })
})

describe('militaryChangeFromDelta2x', () => {
  it('matches Python floor division for positive and negative 2× scale', () => {
    expect(militaryChangeFromDelta2x(44)).toBe(22)
    expect(militaryChangeFromDelta2x(45)).toBe(22)
    expect(militaryChangeFromDelta2x(-107738)).toBe(-53869)
    expect(militaryChangeFromDelta2x(-107737)).toBe(-53869)
  })
})

describe('formatSignedDelta', () => {
  it('prefixes positive values', () => {
    expect(formatSignedDelta(5)).toBe('+5')
    expect(formatSignedDelta(-3)).toBe('-3')
  })
})
