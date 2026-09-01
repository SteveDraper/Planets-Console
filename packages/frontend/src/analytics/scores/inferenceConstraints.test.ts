import { describe, expect, it } from 'vitest'
import {
  formatMilitaryChangeSubtotal,
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

  it('parses tightened interval bounds on a line item', () => {
    const arithmetic = readMilitaryScoreArithmetic({
      observedMilitaryChange: 6674,
      observedMilitaryDelta2x: 13348,
      explainedMilitaryChange: 6674,
      explainedMilitaryDelta2x: 13348,
      matchesObserved: true,
      lineItems: [
        {
          actionId: 'acquired:warship:from:1',
          label: 'Acquired warship from player 1',
          count: 1,
          scoreDelta2xPerUnit: 4996,
          militaryChangePerUnit: 2498,
          scoreDelta2xSubtotal: 4996,
          militaryChangeSubtotal: 2498,
          scoreDelta2xSubtotalMin: 4995,
          scoreDelta2xSubtotalMax: 4997,
          militaryChangeSubtotalMin: 2497,
          militaryChangeSubtotalMax: 2498,
        },
      ],
    })
    expect(arithmetic?.lineItems[0]?.militaryChangeSubtotalMin).toBe(2497)
    expect(arithmetic?.lineItems[0]?.militaryChangeSubtotalMax).toBe(2498)
  })

  it('parses ship-build line items that use comboId', () => {
    const arithmetic = readMilitaryScoreArithmetic({
      observedMilitaryChange: 110,
      observedMilitaryDelta2x: 220,
      explainedMilitaryChange: 110,
      explainedMilitaryDelta2x: 220,
      matchesObserved: true,
      lineItems: [
        {
          comboId: 'combo_13_9_3_6_8_6',
          label: 'Missouri',
          count: 1,
          scoreDelta2xPerUnit: 220,
          militaryChangePerUnit: 110,
          scoreDelta2xSubtotal: 220,
          militaryChangeSubtotal: 110,
        },
      ],
    })
    expect(arithmetic?.lineItems[0]?.actionId).toBe('combo_13_9_3_6_8_6')
    expect(arithmetic?.lineItems[0]?.label).toBe('Missouri')
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

describe('formatMilitaryChangeSubtotal', () => {
  it('formats a point contribution', () => {
    expect(
      formatMilitaryChangeSubtotal({
        actionId: 'defense',
        label: 'Defense post',
        count: 2,
        scoreDelta2xPerUnit: 22,
        militaryChangePerUnit: 11,
        scoreDelta2xSubtotal: 44,
        militaryChangeSubtotal: 22,
      })
    ).toBe('+22')
  })

  it('formats a residual band when min and max differ', () => {
    expect(
      formatMilitaryChangeSubtotal({
        actionId: 'acquired:warship:from:1',
        label: 'Acquired warship from player 1',
        count: 1,
        scoreDelta2xPerUnit: 4996,
        militaryChangePerUnit: 2498,
        scoreDelta2xSubtotal: 4996,
        militaryChangeSubtotal: 2498,
        militaryChangeSubtotalMin: 2497,
        militaryChangeSubtotalMax: 2498,
      })
    ).toBe('+2497 to +2498')
  })
})
