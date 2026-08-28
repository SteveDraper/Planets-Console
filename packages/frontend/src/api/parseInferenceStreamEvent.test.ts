import { describe, expect, it } from 'vitest'
import { parseInferenceStreamEvent } from './parseInferenceStreamEvent'

describe('parseInferenceStreamEvent', () => {
  it('parses solution events with accelerated segment metadata', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'solution',
        segmentId: 'reported_host_turn',
        scoreboardDeltaSource: 'accelerated_segment',
        solutions: [
          {
            objectiveValue: 12,
            actions: [{ actionId: 'a1', label: 'Fighter', count: 2 }],
          },
        ],
      })
    )
    expect(event).toMatchObject({
      type: 'solution',
      segmentId: 'reported_host_turn',
      scoreboardDeltaSource: 'accelerated_segment',
    })
  })

  it('parses solution events with full held top-K', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'solution',
        solutions: [
          {
            objectiveValue: 12,
            actions: [{ actionId: 'a1', label: 'Fighter', count: 2 }],
          },
        ],
      })
    )
    expect(event?.type).toBe('solution')
    if (event?.type === 'solution') {
      expect(event.solutions).toHaveLength(1)
    }
  })

  it('parses ship builds with null optional component ids', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'solution',
        solutions: [
          {
            objectiveValue: 80,
            actions: [],
            shipBuilds: [
              {
                comboId: 'combo_60_4_none_none_0_0',
                label: 'Build Ruby Class Light Cruiser: 2x SuperStarDrive 4',
                count: 1,
                hullId: 60,
                engineId: 4,
                beamId: null,
                torpId: null,
                beamCount: 0,
                launcherCount: 0,
              },
            ],
          },
        ],
      })
    )
    expect(event?.type).toBe('solution')
  })

  it('parses complete events with stopped status', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'complete',
        status: 'stopped',
        displayStatus: 'stopped',
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

  it('parses complete events with final held solutions', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'complete',
        status: 'exact',
        displayStatus: 'success',
        summary: 'Best: built warship',
        solutionCount: 1,
        isComplete: true,
        solutions: [
          {
            objectiveValue: 20,
            actions: [{ actionId: 'a2', label: 'Warship', count: 1 }],
          },
        ],
      })
    )
    expect(event).toMatchObject({
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      isComplete: true,
    })
    if (event?.type === 'complete') {
      expect(event.solutions).toHaveLength(1)
      expect(event.solutions?.[0]?.actions[0]?.actionId).toBe('a2')
    }
  })

  it('parses complete events with leftover and empty placeholders', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'complete',
        status: 'moderate_residual',
        displayStatus: 'moderate_residual',
        summary: 'Moderate military leftover (11)',
        solutionCount: 0,
        isComplete: true,
        solutions: [],
        placeholders: [],
        unexplainedMilitaryDelta2x: 22,
      })
    )
    expect(event).toMatchObject({
      type: 'complete',
      status: 'moderate_residual',
      solutionCount: 0,
      placeholders: [],
      unexplainedMilitaryDelta2x: 22,
    })
  })

  it('parses complete events with first-class fleet torp fields', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'complete',
        status: 'exact',
        displayStatus: 'success',
        summary: 'Best: built warship',
        solutionCount: 1,
        isComplete: true,
        fleetTorpInputStatus: 'applied',
        fleetTorpOverlayBeliefSetTorpIds: [4, 8],
      })
    )
    expect(event).toMatchObject({
      type: 'complete',
      fleetTorpInputStatus: 'applied',
      fleetTorpOverlayBeliefSetTorpIds: [4, 8],
    })
  })

  it('parses global pause events', () => {
    const event = parseInferenceStreamEvent(
      JSON.stringify({
        type: 'globalPause',
        paused: true,
      })
    )
    expect(event).toMatchObject({ type: 'globalPause', paused: true })
  })

  it('rejects complete events without displayStatus', () => {
    expect(() =>
      parseInferenceStreamEvent(
        JSON.stringify({
          type: 'complete',
          status: 'dead',
          summary: 'Player is dead',
          solutionCount: 0,
          isComplete: true,
        })
      )
    ).toThrow(/invalid shape/i)
  })

  it('rejects unknown event types', () => {
    expect(() =>
      parseInferenceStreamEvent(JSON.stringify({ type: 'unknown' }))
    ).toThrow(/unknown event type/i)
  })
})
