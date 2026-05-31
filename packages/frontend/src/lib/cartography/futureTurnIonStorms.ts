import type { StellarCartographyOverlayCircle } from '../../api/bff'
import { ionStormStepDeltaGameLy } from './ionStormMovement'

/** Ion storm travel in game light-years over multiple turns (heading 0 = north). */
export function ionStormGamePositionDeltaLy(
  heading: number,
  warp: number | undefined,
  forwardTurns: number
): { dx: number; dy: number } {
  if (forwardTurns <= 0) return { dx: 0, dy: 0 }
  const { dx, dy } = ionStormStepDeltaGameLy(heading, warp)
  return {
    dx: forwardTurns * dx,
    dy: forwardTurns * dy,
  }
}

export function applyFutureIonStormOverlayPositions(
  circles: readonly StellarCartographyOverlayCircle[],
  forwardTurns: number
): StellarCartographyOverlayCircle[] {
  if (forwardTurns <= 0) return [...circles]
  return circles.map((circle) => {
    if (circle.layer !== 'ion-storms') return circle
    const { dx, dy } = ionStormGamePositionDeltaLy(
      circle.heading ?? 0,
      circle.warp,
      forwardTurns
    )
    return {
      ...circle,
      x: Math.round(circle.x + dx),
      y: Math.round(circle.y + dy),
    }
  })
}
