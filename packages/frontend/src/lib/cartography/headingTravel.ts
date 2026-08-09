/** Per-turn travel delta in game light-years (heading 0 = north, clockwise). */
export function headingTravelDeltaGameLy(
  heading: number,
  travelLy: number
): { dx: number; dy: number } {
  const theta = (heading * Math.PI) / 180
  return {
    dx: travelLy * Math.sin(theta),
    dy: travelLy * Math.cos(theta),
  }
}
