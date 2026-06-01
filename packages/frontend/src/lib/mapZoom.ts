/** Matches React Flow map minZoom / maxZoom. */
export const MAP_ZOOM_MIN = 0.2
export const MAP_ZOOM_MAX = 40

/** React Flow store transform `[translateX, translateY, zoom]`. */
export type ViewportTransform = readonly [number, number, number]

/** Clamps viewport zoom to {@link MAP_ZOOM_MIN} … {@link MAP_ZOOM_MAX}; invalid values become min. */
export function clampMapZoom(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom <= 0) {
    return MAP_ZOOM_MIN
  }
  return Math.min(MAP_ZOOM_MAX, Math.max(MAP_ZOOM_MIN, zoom))
}

/** Reads zoom from a React Flow transform; invalid or missing values clamp to map bounds. */
export function viewportZoomFromTransform(transform: ViewportTransform | null | undefined): number {
  const raw = transform?.[2]
  if (raw === undefined) {
    return MAP_ZOOM_MIN
  }
  return clampMapZoom(raw)
}

const MAP_ZOOM_RATIO = MAP_ZOOM_MAX / MAP_ZOOM_MIN
/** Slider 0 … SLIDER_STEPS; equal steps move equally in log(zoom). */
export const MAP_ZOOM_SLIDER_STEPS = 1000

/**
 * Viewport zoom → slider position. Multiplicative:
 * zoom = MAP_ZOOM_MIN * MAP_ZOOM_RATIO^(slider/SLIDER_STEPS).
 */
export function mapZoomToSlider(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom <= 0) {
    return Math.round(0.5 * MAP_ZOOM_SLIDER_STEPS)
  }
  const z = clampMapZoom(zoom)
  const p = Math.log(z / MAP_ZOOM_MIN) / Math.log(MAP_ZOOM_RATIO)
  if (!Number.isFinite(p)) return Math.round(0.5 * MAP_ZOOM_SLIDER_STEPS)
  return Math.round(p * MAP_ZOOM_SLIDER_STEPS)
}

/** Slider position → zoom (log scale). */
export function mapSliderToZoom(sliderPosition: number): number {
  const p = Math.min(1, Math.max(0, sliderPosition / MAP_ZOOM_SLIDER_STEPS))
  return MAP_ZOOM_MIN * MAP_ZOOM_RATIO ** p
}

/** One header slider step on the log zoom scale (same as keyboard +/-). */
export function stepMapZoomBySliderSteps(zoom: number, deltaSteps: number): number {
  const slider = mapZoomToSlider(zoom) + deltaSteps
  const clamped = Math.min(MAP_ZOOM_SLIDER_STEPS, Math.max(0, slider))
  return mapSliderToZoom(clamped)
}

/** Hold +/-: repeat starts after this delay; tap-only stays one step. */
export const MAP_ZOOM_KEYBOARD_REPEAT_START_MS = 250
/** Hold +/-: repeat tick interval while key stays down. */
export const MAP_ZOOM_KEYBOARD_REPEAT_INTERVAL_MS = 50
/** Hold +/-: add one slider step per tick every this much hold time. */
export const MAP_ZOOM_KEYBOARD_RATE_RAMP_MS = 250

/** Slider steps applied per repeat tick while a zoom key is held. */
export function mapZoomKeyboardStepsPerRepeatTick(holdDurationMs: number): number {
  if (!Number.isFinite(holdDurationMs) || holdDurationMs < 0) return 1
  return 1 + Math.floor(holdDurationMs / MAP_ZOOM_KEYBOARD_RATE_RAMP_MS)
}
