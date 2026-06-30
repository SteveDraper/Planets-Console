import { beforeEach, describe, expect, it } from 'vitest'
import type { AnalyticShellScope } from '../api/bff'
import {
  bumpScoresInferenceRevision,
  noteFleetTorpInputStatusChangeAndShouldBumpRevision,
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

  it('tracks fleet torp status changes per scope for revision bumps', () => {
    expect(
      noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, 'pending')
    ).toBe(true)
    expect(
      noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, 'pending')
    ).toBe(false)
    expect(
      noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, 'applied')
    ).toBe(true)
    expect(noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, null)).toBe(false)
    expect(
      noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeB, 'pending')
    ).toBe(true)
  })

  it('clears fleet torp status memory when revisions reset', () => {
    noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, 'pending')
    useScoresInferenceRevisionStore.getState().resetRevisions()

    expect(
      noteFleetTorpInputStatusChangeAndShouldBumpRevision(scopeA, 'pending')
    ).toBe(true)
  })
})
