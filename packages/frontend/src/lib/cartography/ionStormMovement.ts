/** Per-turn ion storm travel delta in game light-years (heading 0 = north, clockwise). */
export function ionStormStepDeltaGameLy(
  heading: number,
  warp: number | undefined
): { dx: number; dy: number } {
  const stepLy = (warp ?? 0) * (warp ?? 0)
  const theta = (heading * Math.PI) / 180
  return {
    dx: stepLy * Math.sin(theta),
    dy: stepLy * Math.cos(theta),
  }
}
