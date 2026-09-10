import { describe, expect, it } from 'vitest'
import {
  MINEFIELD_STROKE_DASHARRAY,
  minefieldPaintOps,
} from './minefieldPaintOps'
import {
  ANNULUS_FILL_OPACITY,
  INTERIOR_FILL_OPACITY,
  STALE_FILL_OPACITY_FACTOR,
  STROKE_OPACITY,
} from './types'

describe('minefieldPaintOps', () => {
  it('emits nothing when preRadius is <= 0', () => {
    expect(minefieldPaintOps(0, 8, false)).toEqual({ fills: [], strokes: [] })
    expect(minefieldPaintOps(-1, 0, true)).toEqual({ fills: [], strokes: [] })
  })

  it('fills the whole pre disk at annulus opacity when postRadius is 0', () => {
    expect(minefieldPaintOps(12, 0, false)).toEqual({
      fills: [{ kind: 'disk', radius: 12, opacity: ANNULUS_FILL_OPACITY }],
      strokes: [{ radius: 12, opacity: STROKE_OPACITY }],
    })
  })

  it('uses interior fill and one dashed ring when radii are equal', () => {
    expect(minefieldPaintOps(9, 9, false)).toEqual({
      fills: [{ kind: 'disk', radius: 9, opacity: INTERIOR_FILL_OPACITY }],
      strokes: [
        {
          radius: 9,
          opacity: STROKE_OPACITY,
          dasharray: MINEFIELD_STROKE_DASHARRAY,
        },
      ],
    })
  })

  it('emits interior plus annulus fills and solid pre plus dashed post strokes', () => {
    expect(minefieldPaintOps(20, 11, false)).toEqual({
      fills: [
        { kind: 'disk', radius: 11, opacity: INTERIOR_FILL_OPACITY },
        {
          kind: 'annulus',
          outerRadius: 20,
          innerRadius: 11,
          opacity: ANNULUS_FILL_OPACITY,
        },
      ],
      strokes: [
        { radius: 20, opacity: STROKE_OPACITY },
        {
          radius: 11,
          opacity: STROKE_OPACITY,
          dasharray: MINEFIELD_STROKE_DASHARRAY,
        },
      ],
    })
  })

  it('multiplies fill opacities by the stale factor and leaves strokes undimmed', () => {
    const collapsed = minefieldPaintOps(12, 0, true)
    expect(collapsed.fills[0]).toMatchObject({
      opacity: ANNULUS_FILL_OPACITY * STALE_FILL_OPACITY_FACTOR,
    })
    expect(collapsed.strokes[0]?.opacity).toBe(STROKE_OPACITY)

    const equal = minefieldPaintOps(9, 9, true)
    expect(equal.fills[0]).toMatchObject({
      opacity: INTERIOR_FILL_OPACITY * STALE_FILL_OPACITY_FACTOR,
    })
    expect(equal.strokes[0]?.opacity).toBe(STROKE_OPACITY)

    const annulus = minefieldPaintOps(20, 11, true)
    expect(annulus.fills).toEqual([
      {
        kind: 'disk',
        radius: 11,
        opacity: INTERIOR_FILL_OPACITY * STALE_FILL_OPACITY_FACTOR,
      },
      {
        kind: 'annulus',
        outerRadius: 20,
        innerRadius: 11,
        opacity: ANNULUS_FILL_OPACITY * STALE_FILL_OPACITY_FACTOR,
      },
    ])
    expect(annulus.strokes.map((stroke) => stroke.opacity)).toEqual([
      STROKE_OPACITY,
      STROKE_OPACITY,
    ])
  })
})
