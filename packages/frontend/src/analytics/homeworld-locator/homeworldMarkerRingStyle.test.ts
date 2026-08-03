import { describe, expect, it } from 'vitest'
import { homeworldMarkerRings } from './homeworldMarkerRingStyle'
import { CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE } from './constants'

describe('homeworldMarkerRings', () => {
  it('returns a single solid ring for definite markers', () => {
    expect(
      homeworldMarkerRings({
        confidenceTier: CONFIDENCE_DEFINITE,
        isMostProbable: false,
        assertedCue: false,
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
        assertedCue: false,
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
      assertedCue: false,
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
        assertedCue: false,
      })
    ).toHaveLength(1)
  })

  it('adds an amber outer ring when assertedCue is set', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_DEFINITE,
      isMostProbable: false,
      assertedCue: true,
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

  it('adds a cyan selection halo when isSelected', () => {
    const rings = homeworldMarkerRings({
      confidenceTier: CONFIDENCE_POSSIBLE,
      isMostProbable: false,
      assertedCue: false,
      isSelected: true,
    })
    expect(rings[0]).toMatchObject({
      stroke: '#38bdf8',
      strokeDasharray: '2 2',
    })
  })
})
