import { describe, expect, it } from 'vitest'
import { parseLoadAllStreamEvent } from './parseLoadAllStreamEvent'

describe('parseLoadAllStreamEvent', () => {
  it('returns null for blank lines', () => {
    expect(parseLoadAllStreamEvent('')).toBeNull()
    expect(parseLoadAllStreamEvent('   ')).toBeNull()
  })

  it('parses progress events', () => {
    expect(
      parseLoadAllStreamEvent(
        JSON.stringify({
          type: 'progress',
          phase: 'import',
          perspective: 2,
          perspective_total: 11,
          turn: 5,
          turn_total: 111,
          message: 'Turn 5',
        })
      )
    ).toEqual({
      type: 'progress',
      phase: 'import',
      perspective: 2,
      perspective_total: 11,
      turn: 5,
      turn_total: 111,
      message: 'Turn 5',
    })
  })

  it('parses complete events', () => {
    expect(
      parseLoadAllStreamEvent(
        JSON.stringify({
          type: 'complete',
          result: {
            game_id: 628580,
            is_game_finished: true,
            turns_written: 3,
            turns_skipped: 1,
            perspectives_touched: [1, 2],
            final_turn_load_failures: [3],
          },
        })
      )
    ).toEqual({
      type: 'complete',
      result: {
        game_id: 628580,
        is_game_finished: true,
        turns_written: 3,
        turns_skipped: 1,
        perspectives_touched: [1, 2],
        final_turn_load_failures: [3],
      },
    })
  })

  it('parses error events', () => {
    expect(
      parseLoadAllStreamEvent(JSON.stringify({ type: 'error', detail: 'Login required' }))
    ).toEqual({
      type: 'error',
      detail: 'Login required',
    })
  })

  it('throws for unknown event types', () => {
    expect(() => parseLoadAllStreamEvent(JSON.stringify({ type: 'unknown' }))).toThrow(
      'unknown event type'
    )
  })

  it('throws for malformed progress payloads', () => {
    expect(() =>
      parseLoadAllStreamEvent(
        JSON.stringify({
          type: 'progress',
          phase: 'import',
          perspective: -1,
          perspective_total: 11,
          turn: 5,
          turn_total: 111,
          message: 'Turn 5',
        })
      )
    ).toThrow('invalid shape')
  })

  it('throws on invalid JSON', () => {
    expect(() => parseLoadAllStreamEvent('{not json')).toThrow('invalid JSON')
  })
})
