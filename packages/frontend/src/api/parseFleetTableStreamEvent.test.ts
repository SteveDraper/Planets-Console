import { describe, expect, it } from 'vitest'
import {
  fleetTableStreamEventSchema,
  formatFleetTableStreamValidationError,
} from './fleetTableStreamEventSchema'
import { parseFleetTableStreamEvent } from './parseFleetTableStreamEvent'

describe('parseFleetTableStreamEvent', () => {
  it('parses ledger_updated events', () => {
    const event = parseFleetTableStreamEvent(
      JSON.stringify({
        type: 'ledger_updated',
        playerId: 8,
        ledger: {
          playerId: 8,
          playerName: 'Alice',
          records: [],
        },
      })
    )

    expect(event?.type).toBe('ledger_updated')
  })

  it('rejects unknown event types', () => {
    expect(() =>
      parseFleetTableStreamEvent(JSON.stringify({ type: 'unknown', playerId: 8 }))
    ).toThrow(/unknown event type/i)
  })

  it('formats validation errors consistently', () => {
    const result = fleetTableStreamEventSchema.safeParse({ type: 'bogus' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(formatFleetTableStreamValidationError(result.error)).toMatch(/unknown event type/i)
    }
  })
})
