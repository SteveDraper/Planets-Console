import { describe, expect, it } from 'vitest'
import { analyticScopeKey } from './analyticScopeKey'

describe('analyticScopeKey', () => {
  it('keys scope by game, turn, and perspective', () => {
    expect(analyticScopeKey({ gameId: '628580', turn: 111, perspective: 1 })).toBe(
      '628580:111:1'
    )
  })
})
