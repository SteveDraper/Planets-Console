import { CONFIDENCE_DEFINITE } from './constants'
import type { HomeworldMapMarker } from './wireSchema'

const DEFINITE_STROKE = '#f8fafc'
const POSSIBLE_STROKE = '#94a3b8'
const MOST_PROBABLE_STROKE = '#cbd5e1'
/** Location-asserted pin -- distinct from inferred definite (warm amber). */
const ASSERTED_STROKE = '#fbbf24'

export type HomeworldMarkerRing = {
  radiusScale: number
  stroke: string
  strokeWidth: number
  strokeDasharray?: string
  opacity: number
}

export type HomeworldMarkerRingInput = Pick<
  HomeworldMapMarker,
  'confidenceTier' | 'isMostProbable' | 'locationAsserted'
>

function confidenceRings(
  marker: Pick<HomeworldMapMarker, 'confidenceTier' | 'isMostProbable'>
): HomeworldMarkerRing[] {
  if (marker.confidenceTier === CONFIDENCE_DEFINITE) {
    return [
      {
        radiusScale: 1,
        stroke: DEFINITE_STROKE,
        strokeWidth: 1.75,
        opacity: 1,
      },
    ]
  }
  if (marker.isMostProbable) {
    return [
      {
        radiusScale: 1,
        stroke: MOST_PROBABLE_STROKE,
        strokeWidth: 1.5,
        strokeDasharray: '1.5 2',
        opacity: 0.95,
      },
      {
        radiusScale: 0.55,
        stroke: MOST_PROBABLE_STROKE,
        strokeWidth: 1.25,
        strokeDasharray: '1 1.5',
        opacity: 0.9,
      },
    ]
  }
  return [
    {
      radiusScale: 1,
      stroke: POSSIBLE_STROKE,
      strokeWidth: 1.25,
      strokeDasharray: '3 2',
      opacity: 0.75,
    },
  ]
}

/**
 * SVG ring paint for one homeworld map marker.
 * Location-asserted pin adds an outer amber ring.
 */
export function homeworldMarkerRings(marker: HomeworldMarkerRingInput): HomeworldMarkerRing[] {
  const rings = confidenceRings(marker)
  if (marker.locationAsserted) {
    rings.unshift({
      radiusScale: 1.35,
      stroke: ASSERTED_STROKE,
      strokeWidth: 2,
      opacity: 1,
    })
  }
  return rings
}
