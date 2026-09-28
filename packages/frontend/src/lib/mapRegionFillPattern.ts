/**
 * Screen-spaced hatch for a map region fill.
 * The tile is 8px so the pattern stays readable when the map is zoomed out.
 */

export const FILL_PATTERN_PERIOD_PX = 8

/** Light white strokes. The team color stays the dominant cue; the hatch only separates close hues. */
export const FILL_PATTERN_STROKE = 'rgba(255,255,255,0.35)'

export function fillPatternPhase(offset: number): number {
  const period = FILL_PATTERN_PERIOD_PX
  return ((offset % period) + period) % period
}
