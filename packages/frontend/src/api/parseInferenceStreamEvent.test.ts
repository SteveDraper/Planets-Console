import { describe, expect, it } from 'vitest'
import { parseInferenceStreamEvent } from './parseInferenceStreamEvent'

describe('parseInferenceStreamEvent', () => {
  it('parses solution events', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'solution',
        solution: {
          objectiveValue: 12,
          actions: [{ actionId: 'a1', label: 'Fighter', count: 2 }],
        },
      })
    )
    expect(event?.type).toBe('solution')
  })

  it('parses complete events with stopped status', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'complete',
        status: 'stopped',
        summary: 'Build inference halted',
        solutionCount: 0,
        isComplete: true,
      })
    )
    expect(event).toMatchObject({
      type: 'complete',
      status: 'stopped',
      isComplete: true,
    })
  })

  it('rejects unknown event types', () => {
    expect(() =>
      parseInferenceStreamEvent(JSON.stringify({ type: 'unknown' }))
    ).toThrow(/unknown event type/i)
  })
})
