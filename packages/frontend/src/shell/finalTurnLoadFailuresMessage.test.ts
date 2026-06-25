import { describe, it, expect } from 'vitest'
import { formatFinalTurnLoadFailuresMessage } from './finalTurnLoadFailuresMessage'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'

const perspectives = [
  perspectiveRow(1, 'Alice'),
  perspectiveRow(2, 'Bob'),
  perspectiveRow(3, 'Carol'),
]

describe('formatFinalTurnLoadFailuresMessage', () => {
  it('names a single failed perspective with player label', () => {
    expect(formatFinalTurnLoadFailuresMessage([2], perspectives)).toBe(
      'Load-all finished but the final turn could not be fetched for Bob (perspective 2). Retry Load all turns or change turn to load the latest turn manually.'
    )
  })

  it('lists multiple failed perspectives', () => {
    expect(formatFinalTurnLoadFailuresMessage([1, 3], perspectives)).toBe(
      'Load-all finished but the final turn could not be fetched for Alice (perspective 1) and Carol (perspective 3). Retry Load all turns or change turn to load the latest turn manually.'
    )
  })

  it('falls back to perspective slot when player name is unknown', () => {
    expect(formatFinalTurnLoadFailuresMessage([9], perspectives)).toBe(
      'Load-all finished but the final turn could not be fetched for perspective 9. Retry Load all turns or change turn to load the latest turn manually.'
    )
  })
})
