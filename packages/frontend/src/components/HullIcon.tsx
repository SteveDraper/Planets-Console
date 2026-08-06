import { hullImageUrl } from '../concepts/hullImageUrl'
import { cn } from '../lib/utils'

type HullIconProps = {
  hullId: number
  className?: string
  alt?: string
}

/** Shared hull portrait/glyph for scoreboard, fleet table, and map tooltips. */
export function HullIcon({
  hullId,
  className,
  alt = '',
}: HullIconProps) {
  return (
    <img
      src={hullImageUrl(hullId)}
      alt={alt}
      className={cn('object-contain', className)}
      loading="lazy"
    />
  )
}
