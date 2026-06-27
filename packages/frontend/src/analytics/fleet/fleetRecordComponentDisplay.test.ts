import { describe, expect, it } from 'vitest'
import type { FleetComponentCatalog } from './fleetComponentCatalog'
import {
  formatFleetBeamsDisplay,
  formatFleetEngineDisplay,
  formatFleetHullDisplay,
  formatFleetLaunchersDisplay,
} from './fleetRecordComponentDisplay'
import type { FleetTableRecord } from './fleetTableWireSchema'

const catalog: FleetComponentCatalog = {
  hulls: { '46': 'Meteor Class Blockade Runner', '17': 'Large Deep Space Freighter' },
  engines: { '9': 'Transwarp Drive' },
  beams: { '2': 'X-Ray Laser' },
  torpedoes: { '6': 'Mark 4 Photon' },
}

const inferredRecord: FleetTableRecord = {
  recordId: 'rec-inferred',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 33 },
    hull: { kind: 'unknown' },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'known', value: 3 },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [
    {
      comboId: 'combo_46_9_2_6_4_4',
      label: 'Build Meteor Class Blockade Runner: 2x Transwarp Drive, 4x X-Ray Laser',
      solutionRankWeight: 0,
      hullId: 46,
      engineId: 9,
      beamId: 2,
      torpId: 6,
      beamCount: 4,
      launcherCount: 4,
    },
  ],
  displayDefaultOptionSetIndex: 0,
}

describe('fleetRecordComponentDisplay', () => {
  it('resolves hull name and id for inferred builds', () => {
    expect(formatFleetHullDisplay(inferredRecord, catalog)).toEqual({
      hullId: 46,
      label: 'Meteor Class Blockade Runner',
    })
  })

  it('formats engine, beams, and launchers with catalog names', () => {
    expect(formatFleetEngineDisplay(inferredRecord, catalog)).toBe('Transwarp Drive')
    expect(formatFleetBeamsDisplay(inferredRecord, catalog)).toBe('4 X-Ray Laser')
    expect(formatFleetLaunchersDisplay(inferredRecord, catalog)).toBe('4 Mark 4 Photon')
  })

  it('uses observed hull id when field is known', () => {
    const observed: FleetTableRecord = {
      ...inferredRecord,
      fields: {
        ...inferredRecord.fields,
        hull: { kind: 'known', value: 17 },
        engine: { kind: 'known', value: 9 },
      },
      buildOptionSets: [],
      displayDefaultOptionSetIndex: undefined,
    }
    expect(formatFleetHullDisplay(observed, catalog).label).toBe('Large Deep Space Freighter')
    expect(formatFleetEngineDisplay(observed, catalog)).toBe('Transwarp Drive')
  })

  it('shows generic freighter label instead of LDSF catalog name', () => {
    const genericFreighter: FleetTableRecord = {
      ...inferredRecord,
      buildOptionSets: [
        {
          comboId: 'combo_freighter',
          label: 'Freighter',
          solutionRankWeight: 0,
          beamCount: 0,
          launcherCount: 0,
        },
      ],
      displayDefaultOptionSetIndex: 0,
    }
    expect(formatFleetHullDisplay(genericFreighter, catalog)).toEqual({
      hullId: 17,
      label: 'Freighter',
    })
  })
})
