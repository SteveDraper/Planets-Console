import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { fleetFieldConstraintSchema } from './fleetWirePrimitives'
import { fleetTableWireSchema } from './fleetTableWireSchema'
import { parseFleetTableWire } from './parseFleetTableWire'

const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../../test-fixtures/fleet-table-wire.json'
)

type GoldenCase = {
  name: string
  expectedTableWire: unknown
}

describe('fleetTableWireSchema', () => {
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as {
    cases: GoldenCase[]
  }

  it.each(fixture.cases)('parses golden case $name', ({ expectedTableWire }) => {
    const parsed = parseFleetTableWire(expectedTableWire)
    expect(parsed.analyticId).toBe('fleet')
    expect(parsed.defaultActiveOnly).toBe(true)
    expect(parsed.players[0]?.records[0]?.recordId).toBe('rec-active')
  })

  it('rejects payloads that still include core-only events on records', () => {
    const golden = fixture.cases[0]?.expectedTableWire
    expect(golden).toBeDefined()
    const withEvents = structuredClone(golden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    withEvents.players[0]!.records[0]!.events = [{ eventId: 'evt-1', kind: 'sighting' }]

    const result = fleetTableWireSchema.safeParse(withEvents)
    expect(result.success).toBe(false)
  })

  it('rejects missing defaultActiveOnly', () => {
    const golden = fixture.cases[0]?.expectedTableWire
    expect(golden).toBeDefined()
    const withoutDefault = structuredClone(golden) as Record<string, unknown>
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
    const golden = fixture.cases[0]?.expectedTableWire
    expect(golden).toBeDefined()
    const invalid = structuredClone(golden) as {
      players: Array<{ records: Array<Record<string, unknown>> }>
    }
    invalid.players[0]!.records[0]!.disposition = 'vanished'

    expect(() => parseFleetTableWire(invalid)).toThrow(
      'Fleet table record disposition is invalid.'
    )
  })
})
