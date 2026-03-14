import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Matches React Flow map minZoom / maxZoom. */
export const MAP_ZOOM_MIN = 0.2
export const MAP_ZOOM_MAX = 40
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
  const z = Math.min(MAP_ZOOM_MAX, Math.max(MAP_ZOOM_MIN, zoom))
  const p = Math.log(z / MAP_ZOOM_MIN) / Math.log(MAP_ZOOM_RATIO)
  if (!Number.isFinite(p)) return Math.round(0.5 * MAP_ZOOM_SLIDER_STEPS)
  return Math.round(p * MAP_ZOOM_SLIDER_STEPS)
}

/** Slider position → zoom (log scale). */
export function mapSliderToZoom(sliderPosition: number): number {
  const p = Math.min(1, Math.max(0, sliderPosition / MAP_ZOOM_SLIDER_STEPS))
  return MAP_ZOOM_MIN * MAP_ZOOM_RATIO ** p
}
