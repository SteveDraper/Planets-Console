import { headingTravelDeltaGameLy } from './headingTravel'

/** Per-turn ion storm travel delta in game light-years (heading 0 = north, clockwise). */
export function ionStormStepDeltaGameLy(
  heading: number,
  warp: number | undefined
): { dx: number; dy: number } {
  return headingTravelDeltaGameLy(heading, (warp ?? 0) * (warp ?? 0))
}
