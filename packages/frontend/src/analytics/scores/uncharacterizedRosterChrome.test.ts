import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import { militaryChangeFromDelta2x } from './inferenceConstraints'
import {
  formatLatticeBuildLabel,
  formatPlaceholderDepartureLabel,
  formatUnknownLossLeftoverCell,
  formatUnknownLossLeftoverModal,
  leftoverFromInferenceDetail,
  readUnknownLossLeftover,
  uncharacterizedRosterAccessibleLabel,
} from './uncharacterizedRosterChrome'

function rosterDetail(
  overrides: Partial<ScoresInferenceRowDetail> = {}
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'uncharacterized_roster',
    status: 'uncharacterized_roster',
    summary: 'Uncharacterized roster',
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...overrides,
  }
}

describe('unknown-loss leftover formatting', () => {
  it('formats a bound leftover as a lower bound, never a point number', () => {
    const bound = { kind: 'unknown_loss_bound' as const, lowerBound2x: 800 }
    const cell = formatUnknownLossLeftoverCell(bound)
    expect(cell).toBe('≥400')
    expect(cell).not.toBe(String(militaryChangeFromDelta2x(bound.lowerBound2x)))
    expect(formatUnknownLossLeftoverModal(bound)).toContain('at least 400')
    expect(formatUnknownLossLeftoverModal(bound)).toContain(
      'Includes unknown lost-ship contribution'
    )
  })

  it('keeps a zero bound tagged as a bound, not leftover 0', () => {
    const bound = { kind: 'unknown_loss_bound' as const, lowerBound2x: 0 }
    expect(formatUnknownLossLeftoverCell(bound)).toBe('≥0')
    expect(formatUnknownLossLeftoverCell(bound)).not.toBe('0')
    expect(formatUnknownLossLeftoverModal(bound)).toContain('at least 0')
  })

  it('formats a point leftover as a point number', () => {
    const point = { kind: 'point' as const, unexplainedMilitaryDelta2x: 22 }
    expect(formatUnknownLossLeftoverCell(point)).toBe('11')
    expect(formatUnknownLossLeftoverModal(point)).toBe('Military leftover 11.')
    expect(formatUnknownLossLeftoverModal(point)).not.toContain('at least')
  })

  it('rejects a bound leftover that carries a point leftover field', () => {
    expect(
      readUnknownLossLeftover({
        kind: 'unknown_loss_bound',
        lowerBound2x: 800,
        unexplainedMilitaryDelta2x: 800,
      })
    ).toBeNull()
  })
})

describe('uncharacterizedRosterAccessibleLabel', () => {
  it('names the bound leftover and unknown lost-ship contribution', () => {
    expect(
      uncharacterizedRosterAccessibleLabel(
        rosterDetail({ leftover: { kind: 'unknown_loss_bound', lowerBound2x: 800 } })
      )
    ).toBe(
      'Uncharacterized roster. Military leftover at least 400. Includes unknown lost-ship contribution.'
    )
  })

  it('does not treat leftover on the row as unexplainedMilitaryDelta2x', () => {
    const detail = rosterDetail({
      leftover: { kind: 'unknown_loss_bound', lowerBound2x: 800 },
    })
    expect(leftoverFromInferenceDetail(detail)?.kind).toBe('unknown_loss_bound')
    expect(detail.unexplainedMilitaryDelta2x).toBeUndefined()
  })
})

describe('placeholder and lattice labels', () => {
  it('describes placeholder departures without a hull id', () => {
    expect(
      formatPlaceholderDepartureLabel({
        id: 'placeholder_departure',
        shipClass: 'warship',
        count: 1,
        counterpartyPlayerId: 3,
      })
    ).toBe('1 warship departed (counterparty player 3)')
  })

  it('labels lattice builds without plausibility', () => {
    expect(
      formatLatticeBuildLabel({
        id: 'unknown_military_ship',
        hullId: -1,
        count: 1,
        buildSlotUsage: 1,
      })
    ).toBe('Unknown military ship (1)')
    expect(
      formatLatticeBuildLabel({
        id: 'combo_freighter',
        hullId: 0,
        count: 1,
        buildSlotUsage: 1,
      })
    ).toBe('Generic freighter (1)')
  })
})
