import { describe, expect, it } from 'vitest'
import { homeworldMarkerRings } from './homeworldMarkerRingStyle'
import { CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE } from './constants'

describe('homeworldMarkerRings', () => {
  it('returns a single solid ring for definite markers', () => {
    expect(
      homeworldMarkerRings({
        confidenceTier: CONFIDENCE_DEFINITE,
        isMostProbable: false,
        locationAsserted: false,
      })
    ).toEqual([
      {
        radiusScale: 1,
        stroke: '#f8fafc',
        strokeWidth: 1.75,
        opacity: 1,
      },
    ])
  })

  it('returns a dashed ring for ordinary possible markers', () => {
    expect(
      homeworldMarkerRings({
        confidenceTier: CONFIDENCE_POSSIBLE,
        isMostProbable: false,
        locationAsserted: false,
      })
    ).toEqual([
      {
        radiusScale: 1,
        stroke: '#94a3b8',
        strokeWidth: 1.25,
        strokeDasharray: '3 2',
        opacity: 0.75,
      },
    ])
  })

  it('returns double dotted rings for most-probable possible markers', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_POSSIBLE,
      isMostProbable: true,
      locationAsserted: false,
    })
    expect(rings).toHaveLength(2)
    expect(rings[0]).toMatchObject({
      radiusScale: 1,
      strokeDasharray: '1.5 2',
    })
    expect(rings[1]).toMatchObject({
      radiusScale: 0.55,
      strokeDasharray: '1 1.5',
    })
  })

  it('keeps definite styling when isMostProbable is true', () => {
    expect(
      homeworldMarkerRings({
        confidenceTier: CONFIDENCE_DEFINITE,
        isMostProbable: true,
        locationAsserted: false,
      })
    ).toHaveLength(1)
  })

  it('adds an amber outer ring when locationAsserted is set', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_DEFINITE,
      isMostProbable: false,
      locationAsserted: true,
    })
    expect(rings[0]).toMatchObject({
      radiusScale: 1.35,
      stroke: '#fbbf24',
      strokeWidth: 2,
    })
    expect(rings[1]).toMatchObject({
      radiusScale: 1,
      stroke: '#f8fafc',
    })
  })

  it('does not treat ownership-only assertedCue as a homeworld location pin', () => {
    const ownershipOnly = {
      confidenceTier: CONFIDENCE_DEFINITE,
      isMostProbable: false,
      assertedCue: true,
      locationAsserted: false,
    }
    const rings = homeworldMarkerRings(ownershipOnly)
    expect(rings).toHaveLength(1)
    expect(rings[0]).toMatchObject({
      radiusScale: 1,
      stroke: '#f8fafc',
    })
    expect(rings.some((ring) => ring.stroke === '#fbbf24')).toBe(false)
  })

  it('adds a cyan selection halo when isSelected', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_POSSIBLE,
      isMostProbable: false,
      locationAsserted: false,
      isSelected: true,
    })
    expect(rings[0]).toMatchObject({
      radiusScale: 1.4,
      stroke: '#38bdf8',
      strokeDasharray: '2 2',
    })
  })

  it('widens the selection halo when locationAsserted', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_POSSIBLE,
      isMostProbable: false,
      locationAsserted: true,
      isSelected: true,
    })
    expect(rings[0]).toMatchObject({
      radiusScale: 1.65,
      stroke: '#38bdf8',
    })
    expect(rings[1]).toMatchObject({
      radiusScale: 1.35,
      stroke: '#fbbf24',
    })
  })

  it('does not widen the selection halo for ownership-only assertedCue', () => {
    const ownershipOnly = {
      confidenceTier: CONFIDENCE_POSSIBLE,
      isMostProbable: false,
      assertedCue: true,
      locationAsserted: false,
      isSelected: true,
    }
    const rings = homeworldMarkerRings(ownershipOnly)
    expect(rings[0]).toMatchObject({
      radiusScale: 1.4,
      stroke: '#38bdf8',
    })
    expect(rings.some((ring) => ring.stroke === '#fbbf24')).toBe(false)
  })
})
