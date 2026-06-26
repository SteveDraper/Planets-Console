import { describe, expect, it } from 'vitest'
import {
  activeFleetRecords,
  alternateBuildOptionSets,
  formatFleetCountDiscrepancyBanner,
  formatFleetRecordField,
  resolveDefaultBuildOptionSetIndex,
} from './fleetRecordDisplay'
import type { FleetTableRecord } from './fleetTableWireSchema'

const activeRecord: FleetTableRecord = {
  recordId: 'rec-active',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 318 },
    hull: { kind: 'known', value: 13 },
    engine: { kind: 'known', value: 9 },
    beams: { kind: 'options', values: [3, 5] },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'known', value: 4 },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [
    {
      comboId: 'combo_a',
      label: 'Option A',
      solutionRankWeight: 10,
      hullId: 13,
      engineId: 9,
      beamCount: 8,
      launcherCount: 6,
    },
    {
      comboId: 'combo_b',
      label: 'Option B',
      solutionRankWeight: 3,
      hullId: 14,
      engineId: 10,
      beamCount: 4,
      launcherCount: 2,
    },
  ],
  displayDefaultOptionSetIndex: 0,
}

const lostRecord: FleetTableRecord = {
  recordId: 'rec-lost',
  disposition: 'lost',
  qualifiers: {},
  fields: {
    shipId: { kind: 'known', value: 42 },
    hull: { kind: 'unknown' },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'unknown' },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
}

describe('fleetRecordDisplay', () => {
  it('filters to active disposition rows only', () => {
    expect(activeFleetRecords([activeRecord, lostRecord])).toEqual([activeRecord])
  })

  it('uses displayDefaultOptionSetIndex when present', () => {
    expect(resolveDefaultBuildOptionSetIndex(activeRecord)).toBe(0)
  })

  it('falls back to highest solution rank weight when index is absent', () => {
    const record: FleetTableRecord = {
      ...activeRecord,
      displayDefaultOptionSetIndex: undefined,
      buildOptionSets: [
        { label: 'Low', solutionRankWeight: 1, beamCount: 0, launcherCount: 0 },
        { label: 'High', solutionRankWeight: 99, beamCount: 2, launcherCount: 1 },
      ],
    }
    expect(resolveDefaultBuildOptionSetIndex(record)).toBe(1)
  })

  it('fills unknown launchers from the default build option set', () => {
    expect(formatFleetRecordField(activeRecord, 'launchers')).toBe('6')
  })

  it('lists alternate build option sets excluding the default', () => {
    expect(alternateBuildOptionSets(activeRecord).map((option) => option.label)).toEqual([
      'Option B',
    ])
  })

  it('formats discrepancy banner copy', () => {
    expect(formatFleetCountDiscrepancyBanner(2, 1, 111)).toBe(
      'Fleet count discrepancy on turn 111: 2 active rows vs 1 implied by scoreboard'
    )
  })
})
