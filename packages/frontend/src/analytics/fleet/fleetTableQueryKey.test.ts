import { beforeEach, describe, expect, it } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import {
  bumpScoresInferenceRevision,
  scoresInferenceRevisionForScope,
  useScoresInferenceRevisionStore,
} from '../../stores/scoresInferenceRevision'
import { fleetTableQueryKey } from './fleetTableQueryKey'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 3,
  perspective: 1,
}

describe('fleetTableQueryKey', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
  })

  it('includes analytic scope and scores inference revision', () => {
    expect(fleetTableQueryKey(scope, 0)).toEqual([
      'analytic',
      'fleet',
      'table',
      scope,
      0,
    ])
  })

  it('changes when scores inference revision bumps for the same scope', () => {
    const initialKey = fleetTableQueryKey(scope, scoresInferenceRevisionForScope(scope))
    bumpScoresInferenceRevision(scope)
    const nextKey = fleetTableQueryKey(scope, scoresInferenceRevisionForScope(scope))

    expect(nextKey).not.toEqual(initialKey)
    expect(nextKey[4]).toBe(1)
  })
})
