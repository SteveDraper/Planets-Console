/** Column headers for Scores table data cells (matches BFF `TABLE_COLUMNS`). */
export const SCORES_TABLE_DATA_COLUMNS = [
  'Race (player)',
  'Planets',
  'Starbases',
  'War Ships',
  'Freighters',
  'Military',
  'Priority Points',
] as const

export const BUILD_INFERENCE_COLUMN = 'Build inference'

export type ScoresTableDataColumn = (typeof SCORES_TABLE_DATA_COLUMNS)[number]

export function scoresTableCellForColumn(row: string[], column: string): string {
  const index = (SCORES_TABLE_DATA_COLUMNS as readonly string[]).indexOf(column)
  if (index < 0) {
    return ''
  }
  return row[index] ?? ''
}

export function isBuildInferenceColumn(column: string): boolean {
  return column === BUILD_INFERENCE_COLUMN
}
