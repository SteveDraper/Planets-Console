import { describe, expect, it } from 'vitest'
import { fleetFieldConstraintSchema } from './fleetWirePrimitives'
import {
  loadFleetTableWireFixture,
  zodParseableFleetTableWireCases,
} from './loadFleetTableWireFixture'
import { fleetTableWireSchema, parseFleetTableWire } from './fleetTableWireSchema'

describe('fleetTableWireSchema', () => {
  const fixture = loadFleetTableWireFixture()
  const zodParseableCases = zodParseableFleetTableWireCases(fixture.cases)
  const primaryGolden = zodParseableCases[0]?.expectedTableWire

  it.each(zodParseableCases)('parses golden case $name', ({ expectedTableWire }) => {
    const parsed = parseFleetTableWire(expectedTableWire)
    expect(parsed.analyticId).toBe('fleet')
    expect(parsed.defaultActiveOnly).toBe(true)
  })

  it('rejects extra top-level keys on the wire payload', () => {
    expect(primaryGolden).toBeDefined()
    const withExtraTopLevel = structuredClone(primaryGolden) as Record<string, unknown>
    withExtraTopLevel.extraField = 'unexpected'

    const result = fleetTableWireSchema.safeParse(withExtraTopLevel)
    expect(result.success).toBe(false)
  })

  it('rejects extra player-level keys', () => {
    expect(primaryGolden).toBeDefined()
    const withExtraPlayerKey = structuredClone(primaryGolden) as {
      players: Array<Record<string, unknown>>
    }
    withExtraPlayerKey.players[0]!.extraPlayerField = 'unexpected'

    const result = fleetTableWireSchema.safeParse(withExtraPlayerKey)
    expect(result.success).toBe(false)
  })

  it('rejects payloads that still include core-only events on records', () => {
    expect(primaryGolden).toBeDefined()
    const withEvents = structuredClone(primaryGolden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    withEvents.players[0]!.records[0]!.events = [{ eventId: 'evt-1', kind: 'sighting' }]

    const result = fleetTableWireSchema.safeParse(withEvents)
    expect(result.success).toBe(false)
  })

  it('rejects missing defaultActiveOnly', () => {
    expect(primaryGolden).toBeDefined()
    const withoutDefault = structuredClone(primaryGolden) as Record<string, unknown>
    delete withoutDefault.defaultActiveOnly

    expect(() => parseFleetTableWire(withoutDefault)).toThrow(
      'Fleet table payload defaultActiveOnly must be true.'
    )
  })

  it('rejects region field constraints with no locators', () => {
    const result = fleetFieldConstraintSchema.safeParse({ kind: 'region' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error.issues[0]?.message).toBe(
        'Fleet field constraint region requires at least one locator.'
      )
    }
  })

  it('rejects region field constraints with only empty locator lists', () => {
    const result = fleetFieldConstraintSchema.safeParse({
      kind: 'region',
      planetIds: [],
      starbaseCoords: [],
      overlayId: '',
    })
    expect(result.success).toBe(false)
  })

  it('rejects invalid disposition values', () => {
    expect(primaryGolden).toBeDefined()
    const invalid = structuredClone(primaryGolden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    invalid.players[0]!.records[0]!.disposition = 'vanished'

    expect(() => parseFleetTableWire(invalid)).toThrow(
      'Fleet table record disposition is invalid.'
    )
  })

  it('rejects displayDefaultOptionSetIndex out of bounds', () => {
    expect(primaryGolden).toBeDefined()
    const invalid = structuredClone(primaryGolden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    const record = invalid.players[0]!.records[0]!
    record.displayDefaultOptionSetIndex = (record.buildOptionSets as unknown[]).length

    const result = fleetTableWireSchema.safeParse(invalid)
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error.issues[0]?.message).toBe(
        'Fleet table record displayDefaultOptionSetIndex must be less than buildOptionSets.length.'
      )
    }
  })

  it('rejects displayDefaultOptionSetIndex when buildOptionSets is empty', () => {
    expect(primaryGolden).toBeDefined()
    const invalid = structuredClone(primaryGolden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    const record = invalid.players[0]!.records[0]!
    record.buildOptionSets = []
    record.displayDefaultOptionSetIndex = 0

    const result = fleetTableWireSchema.safeParse(invalid)
    expect(result.success).toBe(false)
  })
})
