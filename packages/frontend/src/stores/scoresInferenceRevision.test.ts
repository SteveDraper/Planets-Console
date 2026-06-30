import { beforeEach, describe, expect, it } from 'vitest'
import type { AnalyticShellScope } from '../api/bff'
import {
  bumpScoresInferenceRevision,
  clearBumpMemoryForScope,
  noteSolutionEvidenceChangeAndShouldBumpRevision,
  scoresInferenceRevisionForScope,
  useScoresInferenceRevisionStore,
} from './scoresInferenceRevision'

const scopeA: AnalyticShellScope = {
  gameId: '628580',
  turn: 3,
  perspective: 1,
}

const scopeB: AnalyticShellScope = {
  gameId: '628580',
  turn: 4,
  perspective: 1,
}

const heldSolution = {
  objectiveValue: 100,
  actions: [{ actionId: 'build_fighters', label: 'Fighters', count: 10 }],
}

describe('scoresInferenceRevision', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
  })

  it('starts at zero and bumps monotonically per scope', () => {
    expect(scoresInferenceRevisionForScope(scopeA)).toBe(0)

    bumpScoresInferenceRevision(scopeA)
    expect(scoresInferenceRevisionForScope(scopeA)).toBe(1)

    bumpScoresInferenceRevision(scopeA)
    expect(scoresInferenceRevisionForScope(scopeA)).toBe(2)
  })

  it('keeps revisions independent per scope', () => {
    bumpScoresInferenceRevision(scopeA)
    bumpScoresInferenceRevision(scopeA)
    bumpScoresInferenceRevision(scopeB)

    expect(scoresInferenceRevisionForScope(scopeA)).toBe(2)
    expect(scoresInferenceRevisionForScope(scopeB)).toBe(1)
  })

  it('bumps on first held solutions per player and deduplicates repeats', () => {
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [], null)
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [], null)
    ).toBe(false)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], null)
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], null)
    ).toBe(false)
  })

  it('tracks fleet torp status changes per player within scope', () => {
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [], 'pending')
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [], 'pending')
    ).toBe(false)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [], 'applied')
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 6, [], 'pending')
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeB, 8, [], 'pending')
    ).toBe(true)
  })

  it('clears per-player bump memory for a scope on reconnect', () => {
    noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], 'pending')
    clearBumpMemoryForScope(scopeA)

    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], 'pending')
    ).toBe(true)
    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 6, [], 'pending')
    ).toBe(true)
  })

  it('clears bump memory when revisions reset', () => {
    noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], 'pending')
    useScoresInferenceRevisionStore.getState().resetRevisions()

    expect(
      noteSolutionEvidenceChangeAndShouldBumpRevision(scopeA, 8, [heldSolution], 'pending')
    ).toBe(true)
  })
})
