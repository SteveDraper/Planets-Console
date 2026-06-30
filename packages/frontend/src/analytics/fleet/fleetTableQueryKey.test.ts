import { describe, expect, it } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { fleetTableQueryKey } from './fleetTableQueryKey'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 3,
  perspective: 1,
}

describe('fleetTableQueryKey', () => {
  it('includes analytic scope only', () => {
    expect(fleetTableQueryKey(scope)).toEqual(['analytic', 'fleet', 'table', scope])
  })

  it('does not include scores inference revision', () => {
    const key = fleetTableQueryKey(scope)
    expect(key).toHaveLength(4)
    expect(key.includes('scoresInferenceRevision' as never)).toBe(false)
  })
})
