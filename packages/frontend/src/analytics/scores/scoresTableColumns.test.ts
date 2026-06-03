import { describe, expect, it } from 'vitest'
import {
  BUILD_INFERENCE_COLUMN,
  scoresTableCellForColumn,
} from './scoresTableColumns'

describe('scoresTableCellForColumn', () => {
  const row = [
    'Federation (alice)',
    '10 (+1)',
    '5',
    '3',
    '2',
    '1000 (-50)',
    '217 (+54)',
  ]

  it('maps data columns by name, not by header position', () => {
    expect(scoresTableCellForColumn(row, 'Priority Points')).toBe('217 (+54)')
    expect(scoresTableCellForColumn(row, 'Military')).toBe('1000 (-50)')
    expect(scoresTableCellForColumn(row, BUILD_INFERENCE_COLUMN)).toBe('')
  })
})
