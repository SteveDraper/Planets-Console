import { CONFIDENCE_DEFINITE } from './constants'
import type { HomeworldMapMarker } from './wireSchema'

const DEFINITE_STROKE = '#f8fafc'
const POSSIBLE_STROKE = '#94a3b8'
const MOST_PROBABLE_STROKE = '#cbd5e1'
/** Asserted-strength cue -- distinct from inferred definite (warm amber). */
const ASSERTED_STROKE = '#fbbf24'
const SELECTED_STROKE = '#38bdf8'

export type HomeworldMarkerRing = {
  radiusScale: number
  stroke: string
  strokeWidth: number
  strokeDasharray?: string
  opacity: number
}

export type HomeworldMarkerRingInput = Pick<
  HomeworldMapMarker,
  'confidenceTier' | 'isMostProbable' | 'assertedCue'
> & {
  /** Ephemeral UI highlight when the panel/table row is focused. */
  isSelected?: boolean
}

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
 * Asserted cue adds an outer amber ring; selection adds a cyan halo.
 */
export function homeworldMarkerRings(marker: HomeworldMarkerRingInput): HomeworldMarkerRing[] {
  const rings = confidenceRings(marker)
  if (marker.assertedCue) {
    rings.unshift({
      radiusScale: 1.35,
      stroke: ASSERTED_STROKE,
      strokeWidth: 2,
      opacity: 1,
    })
  }
  if (marker.isSelected) {
    rings.unshift({
      radiusScale: marker.assertedCue ? 1.65 : 1.4,
      stroke: SELECTED_STROKE,
      strokeWidth: 1.5,
      strokeDasharray: '2 2',
      opacity: 0.95,
    })
  }
  return rings
}
