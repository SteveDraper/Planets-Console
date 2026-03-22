import { describe, expect, it } from 'vitest'
import {
  buildMineralRows,
  buildPlanetTitleLine,
  DEFAULT_PLANET_LABEL_OPTIONS,
  formatNativesLine,
  getPlanetDataAvailability,
  planetLabelOptionsShowAnyLabel,
} from './planetMapLabelModel'

describe('planetMapLabelModel', () => {
  it('defaults to only planet id for label options', () => {
    expect(DEFAULT_PLANET_LABEL_OPTIONS.includePlanetId).toBe(true)
    expect(DEFAULT_PLANET_LABEL_OPTIONS.includePlanetName).toBe(false)
    expect(DEFAULT_PLANET_LABEL_OPTIONS.includeCoordinates).toBe(false)
    expect(DEFAULT_PLANET_LABEL_OPTIONS.detailsLevel).toBe('none')
  })

  it('planetLabelOptionsShowAnyLabel is false when nothing is selected', () => {
    expect(
      planetLabelOptionsShowAnyLabel({
        includePlanetId: false,
        includePlanetName: false,
        includeCoordinates: false,
        detailsLevel: 'none',
      })
    ).toBe(false)
  })

  it('buildPlanetTitleLine joins id, name, and coordinates in order with spaces', () => {
    const planet = { id: 42, name: 'Homeworld' }
    const line = buildPlanetTitleLine(
      {
        includePlanetId: true,
        includePlanetName: true,
        includeCoordinates: true,
        detailsLevel: 'none',
      },
      planet,
      100,
      200
    )
    expect(line).toBe('p42 Homeworld (100, 200)')
  })

  it('buildPlanetTitleLine infers id from node id when planet payload is missing', () => {
    const line = buildPlanetTitleLine(
      {
        includePlanetId: true,
        includePlanetName: false,
        includeCoordinates: false,
        detailsLevel: 'none',
      },
      undefined,
      0,
      0,
      'base-map:p7'
    )
    expect(line).toBe('p7')
  })

  it('buildMineralRows appends % to density values', () => {
    const rows = buildMineralRows({
      densityneutronium: 52,
      densityduranium: 0,
      densitytritanium: -1,
    } as Record<string, unknown>)
    const n = rows.find((r) => r.label === 'Neutronium')
    expect(n?.density).toBe('52%')
    expect(rows.find((r) => r.label === 'Duranium')?.density).toBe('0%')
    expect(rows.find((r) => r.label === 'Tritanium')?.density).toBe('-1%')
  })

  it('getPlanetDataAvailability follows temp, owner, and neutronium sentinels', () => {
    expect(getPlanetDataAvailability(undefined)).toBe('NO_DATA')

    expect(getPlanetDataAvailability({ ownerid: 0, temp: -1 })).toBe('NO_DATA')
    expect(getPlanetDataAvailability({ ownerid: 3, temp: -1 })).toBe('OWNERSHIP_ONLY')

    expect(getPlanetDataAvailability({ temp: 50, neutronium: -1 })).toBe('BASIC_INFO')
    expect(getPlanetDataAvailability({ temp: 0, neutronium: -1, ownerid: 1 })).toBe('BASIC_INFO')

    expect(getPlanetDataAvailability({ neutronium: 0 })).toBe('FULL_INFO')
    expect(getPlanetDataAvailability({ temp: 20, neutronium: 0, ownerid: 1 })).toBe('FULL_INFO')
    expect(getPlanetDataAvailability({ neutronium: 100 })).toBe('FULL_INFO')
  })

  it('buildPlanetTitleLine includes name when planet id is a string from JSON', () => {
    const line = buildPlanetTitleLine(
      {
        includePlanetId: true,
        includePlanetName: true,
        includeCoordinates: false,
        detailsLevel: 'none',
      },
      { id: '42', name: 'Xenon' } as Record<string, unknown>,
      0,
      0
    )
    expect(line).toBe('p42 Xenon')
  })

  it('formatNativesLine is only None when nativetype is NONE (0), with no counts', () => {
    expect(
      formatNativesLine({
        nativetype: 0,
        nativeracename: 'Humanoid',
        nativeclans: 5000,
      } as Record<string, unknown>)
    ).toBe('Natives: None')
  })

  it('formatNativesLine shows race and clans when nativetype is not NONE', () => {
    expect(
      formatNativesLine({
        nativetype: 2,
        nativeracename: 'Bovinoid',
        nativeclans: 120,
      } as Record<string, unknown>)
    ).toBe('Natives: Bovinoid / 120')
  })
})
