import { describe, expect, it } from 'vitest'
import { parseFleetTableStreamEvent } from './parseFleetTableStreamEvent'

describe('parseFleetTableStreamEvent', () => {
  it('parses ledger_updated with player scope', () => {
    const event = parseFleetTableStreamEvent(
      JSON.stringify({
        type: 'ledger_updated',
        playerId: 8,
        ledger: {
          playerId: 8,
          playerName: 'dougp314',
          records: [],
        },
      })
    )
    expect(event).toEqual({
      type: 'ledger_updated',
      playerId: 8,
      ledger: {
        playerId: 8,
        playerName: 'dougp314',
        records: [],
      },
    })
  })

  it('parses provenance and complete terminal events', () => {
    const provenance = parseFleetTableStreamEvent(
      JSON.stringify({
        type: 'provenance',
        playerId: 6,
        turnEvidenceAtN: true,
        priorLedgerAtNMinus1: false,
        isFinal: false,
      })
    )
    expect(provenance?.type).toBe('provenance')

    const complete = parseFleetTableStreamEvent(
      JSON.stringify({
        type: 'complete',
        playerId: 6,
        isFinal: false,
        summary: 'Fleet ledger materialized with open provenance legs.',
      })
    )
    expect(complete?.type).toBe('complete')
  })

  it('rejects unknown event types', () => {
    expect(() => parseFleetTableStreamEvent(JSON.stringify({ type: 'unknown' }))).toThrow(
      'Fleet table stream returned unknown event type.'
    )
  })
})
