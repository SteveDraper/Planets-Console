import { describe, expect, it } from 'vitest'
import {
  clampMapZoom,
  MAP_ZOOM_KEYBOARD_RATE_RAMP_MS,
  MAP_ZOOM_MAX,
  MAP_ZOOM_MIN,
  MAP_ZOOM_SLIDER_STEPS,
  mapZoomKeyboardStepsPerRepeatTick,
  mapZoomToSlider,
  stepMapZoomBySliderSteps,
  viewportZoomFromTransform,
} from './mapZoom'

describe('clampMapZoom', () => {
  it('clamps finite zoom to map bounds', () => {
    expect(clampMapZoom(1.5)).toBe(1.5)
    expect(clampMapZoom(MAP_ZOOM_MIN)).toBe(MAP_ZOOM_MIN)
    expect(clampMapZoom(MAP_ZOOM_MAX)).toBe(MAP_ZOOM_MAX)
    expect(clampMapZoom(0.01)).toBe(MAP_ZOOM_MIN)
    expect(clampMapZoom(999)).toBe(MAP_ZOOM_MAX)
  })

  it('falls back to MAP_ZOOM_MIN for invalid values', () => {
    expect(clampMapZoom(NaN)).toBe(MAP_ZOOM_MIN)
    expect(clampMapZoom(0)).toBe(MAP_ZOOM_MIN)
    expect(clampMapZoom(-1)).toBe(MAP_ZOOM_MIN)
  })
})

describe('viewportZoomFromTransform', () => {
  it('reads zoom from transform and clamps to map bounds', () => {
    expect(viewportZoomFromTransform([0, 0, 1.5])).toBe(1.5)
    expect(viewportZoomFromTransform([0, 0, MAP_ZOOM_MIN])).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform([0, 0, MAP_ZOOM_MAX])).toBe(MAP_ZOOM_MAX)
    expect(viewportZoomFromTransform([0, 0, 0.01])).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform([0, 0, 999])).toBe(MAP_ZOOM_MAX)
  })

  it('falls back to MAP_ZOOM_MIN for missing or invalid transform', () => {
    expect(viewportZoomFromTransform(undefined)).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform(null)).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform([0, 0, NaN])).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform([0, 0, 0])).toBe(MAP_ZOOM_MIN)
    expect(viewportZoomFromTransform([0, 0, -1])).toBe(MAP_ZOOM_MIN)
  })
})

describe('stepMapZoomBySliderSteps', () => {
  it('moves one log-scale slider step per keypress', () => {
    const zoom = 1
    const slider = mapZoomToSlider(zoom)
    const up = stepMapZoomBySliderSteps(zoom, 1)
    const down = stepMapZoomBySliderSteps(up, -1)
    expect(mapZoomToSlider(up)).toBe(slider + 1)
    expect(mapZoomToSlider(down)).toBe(slider)
  })

  it('ramps repeat steps linearly every 250ms of hold time', () => {
    expect(mapZoomKeyboardStepsPerRepeatTick(0)).toBe(1)
    expect(mapZoomKeyboardStepsPerRepeatTick(249)).toBe(1)
    expect(mapZoomKeyboardStepsPerRepeatTick(250)).toBe(2)
    expect(mapZoomKeyboardStepsPerRepeatTick(499)).toBe(2)
    expect(mapZoomKeyboardStepsPerRepeatTick(500)).toBe(3)
    expect(mapZoomKeyboardStepsPerRepeatTick(MAP_ZOOM_KEYBOARD_RATE_RAMP_MS * 4)).toBe(5)
  })

  it('clamps at min and max zoom', () => {
    expect(stepMapZoomBySliderSteps(MAP_ZOOM_MIN, -1)).toBe(MAP_ZOOM_MIN)
    expect(stepMapZoomBySliderSteps(MAP_ZOOM_MAX, 1)).toBe(MAP_ZOOM_MAX)
    expect(mapZoomToSlider(stepMapZoomBySliderSteps(MAP_ZOOM_MIN, -5))).toBe(0)
    expect(mapZoomToSlider(stepMapZoomBySliderSteps(MAP_ZOOM_MAX, 5))).toBe(
      MAP_ZOOM_SLIDER_STEPS
    )
  })
})
