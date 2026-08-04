import { describe, expect, it } from 'vitest'
import { flowPointNeedsPan } from './mapFlowGeometry'

describe('flowPointNeedsPan', () => {
  const centered = {
    x: 400,
    y: 300,
    zoom: 1,
    width: 800,
    height: 600,
  }

  it('is false when the flow point is inside the pane', () => {
    // pane = flow * zoom + translation → flow 0 projects to (400, 300)
    expect(flowPointNeedsPan(0, 0, centered)).toBe(false)
  })

  it('is false when the point sits on the top-left corner (still in view)', () => {
    expect(flowPointNeedsPan(-400, -300, centered)).toBe(false)
  })

  it('is true when left of the pane', () => {
    expect(flowPointNeedsPan(-401, 0, centered)).toBe(true)
  })

  it('is true when right of / on the right edge of the pane', () => {
    // paneX = flowX + 400; width 800 → paneX >= 800 is outside
    expect(flowPointNeedsPan(400, 0, centered)).toBe(true)
  })

  it('is true when above the pane', () => {
    expect(flowPointNeedsPan(0, -301, centered)).toBe(true)
  })

  it('is true when below / on the bottom edge of the pane', () => {
    expect(flowPointNeedsPan(0, 300, centered)).toBe(true)
  })

  it('respects zoom when projecting to pane space', () => {
    const zoomed = { ...centered, zoom: 2, x: 0, y: 0 }
    // pane = flow * 2; (50, 50) → (100, 100) still inside 800×600
    expect(flowPointNeedsPan(50, 50, zoomed)).toBe(false)
    // (450, 50) → (900, 100) outside width
    expect(flowPointNeedsPan(450, 50, zoomed)).toBe(true)
  })

  it('treats invalid zoom as clamped positive scale (still decidable)', () => {
    expect(flowPointNeedsPan(0, 0, { ...centered, zoom: 0, x: 0, y: 0 })).toBe(false)
    expect(flowPointNeedsPan(5000, 0, { ...centered, zoom: NaN, x: 0, y: 0 })).toBe(true)
  })
})
