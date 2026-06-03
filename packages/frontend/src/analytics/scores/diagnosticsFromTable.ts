import type { AnalyticShellScope, ScoresInferenceRowDetail, TableDataResponse } from '../../api/bff'
import { isScoresInferenceRowDetail } from '../../api/bff'
import type { ScoresAnalyticDiagnostics } from '../../stores/analyticDiagnostics'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function readTurn(diagnostics: Record<string, unknown>): number | null {
  if (typeof diagnostics.turn === 'number') {
    return diagnostics.turn
  }
  const constraints = diagnostics.constraints
  if (isRecord(constraints) && typeof constraints.turn === 'number') {
    return constraints.turn
  }
  return null
}

function readSection(
  diagnostics: Record<string, unknown>,
  key: 'constraints' | 'actionCatalog' | 'solver'
): Record<string, unknown> | undefined {
  const direct = diagnostics[key]
  if (isRecord(direct)) {
    return direct
  }
  return undefined
}

function playerDiagnosticsFromRow(
  racePlayer: string,
  detail: ScoresInferenceRowDetail,
  rowIndex: number
): ScoresAnalyticDiagnostics['players'][number] | null {
  const diagnostics = isRecord(detail.diagnostics) ? detail.diagnostics : {}
  const turn = readTurn(diagnostics)
  if (turn == null) {
    return null
  }

  const playerId =
    typeof detail.playerId === 'number'
      ? detail.playerId
      : isRecord(diagnostics.constraints) && typeof diagnostics.constraints.playerId === 'number'
        ? diagnostics.constraints.playerId
        : -(rowIndex + 1)

  return {
    playerId,
    racePlayer,
    status: detail.status,
    summary: detail.summary,
    turn,
    constraints: readSection(diagnostics, 'constraints'),
    actionCatalog: readSection(diagnostics, 'actionCatalog'),
    solver: readSection(diagnostics, 'solver'),
    diagnostics,
  }
}

export function scoresDiagnosticsFromTable(
  data: TableDataResponse,
  scope: AnalyticShellScope
): ScoresAnalyticDiagnostics | null {
  if (data.analyticId !== 'scores' || data.includeBuildInference !== true) {
    return null
  }
  const inferenceByRow = data.inferenceByRow
  if (inferenceByRow == null) {
    return null
  }

  const players = data.rows.flatMap((row, rowIndex) => {
    const detail = inferenceByRow[rowIndex]
    if (detail == null || !isScoresInferenceRowDetail(detail)) {
      return []
    }
    const parsed = playerDiagnosticsFromRow(String(row[0] ?? ''), detail, rowIndex)
    return parsed != null ? [parsed] : []
  })

  return {
    scope,
    capturedAt: new Date().toISOString(),
    includeBuildInference: true,
    players,
  }
}
