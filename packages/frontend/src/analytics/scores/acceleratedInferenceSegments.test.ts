import { describe, expect, it } from 'vitest'
import {
  acceleratedSegmentTitle,
  readAcceleratedInferenceSegments,
} from './acceleratedInferenceSegments'

describe('readAcceleratedInferenceSegments', () => {
  it('returns null when accelerated segments are absent', () => {
    expect(readAcceleratedInferenceSegments({})).toBeNull()
    expect(readAcceleratedInferenceSegments({ accelerated_segments: [] })).toBeNull()
  })

  it('parses segment payloads and sorts by host turn', () => {
    const segments = readAcceleratedInferenceSegments({
      accelerated_segments: [
        {
          segmentId: 'reported_host_turn',
          hostTurn: 2,
          status: 'exact',
          solutionCount: 1,
          militaryDelta2x: 220,
          warshipDelta: 1,
          freighterDelta: 0,
          solutions: [
            {
              objectiveValue: 100,
              actions: [],
              militaryScoreArithmetic: {
                observedMilitaryChange: 110,
                observedMilitaryDelta2x: 220,
                explainedMilitaryChange: 110,
                explainedMilitaryDelta2x: 220,
                matchesObserved: true,
                lineItems: [
                  {
                    comboId: 'combo_13_9_3_6_8_6',
                    label: 'Missouri',
                    count: 1,
                    scoreDelta2xPerUnit: 220,
                    militaryChangePerUnit: 110,
                    scoreDelta2xSubtotal: 220,
                    militaryChangeSubtotal: 110,
                  },
                ],
              },
            },
          ],
        },
        {
          segmentId: 'accel_window',
          hostTurn: 1,
          status: 'exact',
          solutionCount: 1,
          militaryDelta2x: 220,
          warshipDelta: 0,
          freighterDelta: 0,
          solutions: [
            {
              objectiveValue: 999,
              actions: [
                {
                  actionId: 'planet_defense',
                  label: 'Planet defense post',
                  count: 10,
                },
              ],
              militaryScoreArithmetic: {
                observedMilitaryChange: 110,
                observedMilitaryDelta2x: 220,
                explainedMilitaryChange: 110,
                explainedMilitaryDelta2x: 220,
                matchesObserved: true,
                lineItems: [
                  {
                    actionId: 'planet_defense',
                    label: 'Planet defense post',
                    count: 10,
                    scoreDelta2xPerUnit: 22,
                    militaryChangePerUnit: 11,
                    scoreDelta2xSubtotal: 220,
                    militaryChangeSubtotal: 110,
                  },
                ],
              },
            },
          ],
        },
      ],
    })

    expect(segments).not.toBeNull()
    expect(segments).toHaveLength(2)
    expect(segments?.[0].segmentId).toBe('accel_window')
    expect(segments?.[1].segmentId).toBe('reported_host_turn')
    expect(segments?.[1].solutions[0].militaryScoreArithmetic?.lineItems[0].actionId).toBe(
      'combo_13_9_3_6_8_6'
    )
  })
})

describe('acceleratedSegmentTitle', () => {
  it('labels accelerated window and reported host turn segments', () => {
    expect(
      acceleratedSegmentTitle(
        {
          segmentId: 'accel_window',
          hostTurn: 1,
          status: 'exact',
          solutionCount: 1,
          militaryDelta2x: 220,
          warshipDelta: 0,
          freighterDelta: 0,
          solutions: [],
        },
        3
      )
    ).toBe('Host turn 1 (accelerated window)')

    expect(
      acceleratedSegmentTitle(
        {
          segmentId: 'reported_host_turn',
          hostTurn: 2,
          status: 'exact',
          solutionCount: 1,
          militaryDelta2x: 220,
          warshipDelta: 1,
          freighterDelta: 0,
          solutions: [],
        },
        3
      )
    ).toBe('Host turn 2 (on scoreboard row turn 3)')
  })
})
