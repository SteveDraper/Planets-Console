import { describe, expect, it } from 'vitest'
import { formatFleetHoverWarpLabel } from './FleetLocationRingTooltipBody'

describe('formatFleetHoverWarpLabel', () => {
  it('formats known warp as (wX)', () => {
    expect(formatFleetHoverWarpLabel(9)).toBe('(w9)')
    expect(formatFleetHoverWarpLabel(1)).toBe('(w1)')
  })

  it('formats motionless/unknown warp as (-)', () => {
    expect(formatFleetHoverWarpLabel(null)).toBe('(-)')
  })
})
