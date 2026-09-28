import type { MapRegionFillPattern } from '../api/mapRegionOverlayTypes'
import { FILL_PATTERN_STROKE } from './mapRegionFillPattern'

export function FillPatternMarks({
  pattern,
  stroke = FILL_PATTERN_STROKE,
}: {
  pattern: MapRegionFillPattern
  stroke?: string
}) {
  if (pattern === 'solid') return null
  if (pattern === 'dots') {
    return <circle cx={4} cy={4} r={1.25} fill={stroke} />
  }
  const d =
    pattern === 'forward'
      ? 'M-1,9 L9,-1'
      : pattern === 'back'
        ? 'M-1,-1 L9,9'
        : pattern === 'horizontal'
          ? 'M0,4 L8,4'
          : 'M4,0 L4,8'
  return <path d={d} stroke={stroke} strokeWidth={1.5} fill="none" />
}
