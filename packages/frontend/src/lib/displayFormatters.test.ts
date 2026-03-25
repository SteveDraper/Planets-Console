import { describe, it, expect } from 'vitest'
import { formatStoredGameRowLabel, formatViewpointRowLabel } from './displayFormatters'

describe('formatViewpointRowLabel', () => {
  it('shows player name only in player_names_only mode', () => {
    expect(formatViewpointRowLabel('player_names_only', 'alice', 'The Feds')).toBe('alice')
  })

  it('shows race name or a placeholder when race is unknown in race_names_only mode', () => {
    expect(formatViewpointRowLabel('race_names_only', 'alice', 'The Feds')).toBe('The Feds')
    expect(formatViewpointRowLabel('race_names_only', 'alice', null)).toBe('—')
  })

  it('combines when both requested and race is known', () => {
    expect(formatViewpointRowLabel('player_and_race_names', 'alice', 'The Feds')).toBe(
      'The Feds (alice)'
    )
    expect(formatViewpointRowLabel('player_and_race_names', 'alice', null)).toBe('alice')
  })
})

describe('formatStoredGameRowLabel', () => {
  it('formats ids, names, and combined labels', () => {
    expect(formatStoredGameRowLabel('sector_ids_only', '628580', 'Serada')).toBe('628580')
    expect(formatStoredGameRowLabel('sector_names_only', '628580', 'Serada')).toBe('Serada')
    expect(formatStoredGameRowLabel('sector_names_only', '628580', undefined)).toBe('628580')
    expect(formatStoredGameRowLabel('both_ids_and_names', '628580', 'Serada')).toBe(
      'Serada (628580)'
    )
    expect(formatStoredGameRowLabel('both_ids_and_names', '628580', null)).toBe('628580')
  })
})
