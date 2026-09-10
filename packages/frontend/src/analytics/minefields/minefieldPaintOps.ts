/**
 * Degenerate fill and stroke ops for one minefield given pre/post radii
 * in the same space (game or pane). Color and stroke width stay with the pane.
 */

import {
  ANNULUS_FILL_OPACITY,
  INTERIOR_FILL_OPACITY,
  STALE_FILL_OPACITY_FACTOR,
  STROKE_OPACITY,
} from './types'

export const MINEFIELD_STROKE_DASHARRAY = '4 3'

export type MinefieldDiskFillOp = {
  kind: 'disk'
  radius: number
  opacity: number
}

export type MinefieldAnnulusFillOp = {
  kind: 'annulus'
  outerRadius: number
  innerRadius: number
  opacity: number
}

export type MinefieldFillOp = MinefieldDiskFillOp | MinefieldAnnulusFillOp

export type MinefieldStrokeOp = {
  radius: number
  opacity: number
  dasharray?: string
}

export type MinefieldPaintOps = {
  fills: readonly MinefieldFillOp[]
  strokes: readonly MinefieldStrokeOp[]
}

function fillOpacity(base: number, stale: boolean): number {
  return stale ? base * STALE_FILL_OPACITY_FACTOR : base
}

export function minefieldPaintOps(
  preRadius: number,
  postRadius: number,
  stale: boolean
): MinefieldPaintOps {
  if (preRadius <= 0) {
    return { fills: [], strokes: [] }
  }

  if (postRadius <= 0) {
    return {
      fills: [
        {
          kind: 'disk',
          radius: preRadius,
          opacity: fillOpacity(ANNULUS_FILL_OPACITY, stale),
        },
      ],
      strokes: [{ radius: preRadius, opacity: STROKE_OPACITY }],
    }
  }

  if (preRadius === postRadius) {
    return {
      fills: [
        {
          kind: 'disk',
          radius: postRadius,
          opacity: fillOpacity(INTERIOR_FILL_OPACITY, stale),
        },
      ],
      strokes: [
        {
          radius: preRadius,
          opacity: STROKE_OPACITY,
          dasharray: MINEFIELD_STROKE_DASHARRAY,
        },
      ],
    }
  }

  return {
    fills: [
      {
        kind: 'disk',
        radius: postRadius,
        opacity: fillOpacity(INTERIOR_FILL_OPACITY, stale),
      },
      {
        kind: 'annulus',
        outerRadius: preRadius,
        innerRadius: postRadius,
        opacity: fillOpacity(ANNULUS_FILL_OPACITY, stale),
      },
    ],
    strokes: [
      { radius: preRadius, opacity: STROKE_OPACITY },
      {
        radius: postRadius,
        opacity: STROKE_OPACITY,
        dasharray: MINEFIELD_STROKE_DASHARRAY,
      },
    ],
  }
}
