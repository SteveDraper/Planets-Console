import { describe, expect, it } from 'vitest'
import { CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE } from './constants'
import { homeworldMarkerRings } from './homeworldMarkerRingStyle'

describe('homeworldMarkerRings', () => {
  it('returns a single solid ring for definite markers', () => {
    expect(
      homeworldMarkerRings({
        confidenceTier: CONFIDENCE_DEFINITE,
        isMostProbable: false,
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
      })
    ).toHaveLength(1)
  })
})
