import { describe, expect, it } from 'vitest'
import {
  MAP_ZOOM_KEYBOARD_RATE_RAMP_MS,
  MAP_ZOOM_MAX,
  MAP_ZOOM_MIN,
  MAP_ZOOM_SLIDER_STEPS,
  mapZoomKeyboardStepsPerRepeatTick,
  mapZoomToSlider,
  stepMapZoomBySliderSteps,
} from './utils'

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
