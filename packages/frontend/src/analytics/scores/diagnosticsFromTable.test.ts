import { describe, expect, it } from 'vitest'
import type { TableDataResponse } from '../../api/bff'
import { scoresDiagnosticsFromTable } from './diagnosticsFromTable'

describe('scoresDiagnosticsFromTable', () => {
  it('returns null when build inference is disabled', () => {
    const data: TableDataResponse = {
      analyticId: 'scores',
      columns: ['Race (player)'],
      rows: [['koshling']],
    }
    expect(
      scoresDiagnosticsFromTable(data, { gameId: '628580', turn: 111, perspective: 1 })
    ).toBeNull()
  })

  it('extracts per-player constraints, catalog, and solver diagnostics', () => {
    const data: TableDataResponse = {
      analyticId: 'scores',
      includeBuildInference: true,
      columns: ['Race (player)', 'Build inference'],
      rows: [['koshling', '']],
      inferenceByRow: [
        {
          playerId: 8,
          displayStatus: 'failure',
          status: 'no_exact_solution',
          summary: 'No feasible build explanation found',
          solutionCount: 0,
          isComplete: true,
          solutions: [],
          diagnostics: {
            turn: 111,
            constraints: { playerId: 8, militaryDelta2x: -107738 },
            actionCatalog: { catalogSize: 9, actions: [{ id: 'planet_defense_posts_added_total' }] },
            solver: { status: 'no_exact_solution', solver_status: 'INFEASIBLE' },
          },
        },
      ],
    }

    const snapshot = scoresDiagnosticsFromTable(data, {
      gameId: '628580',
      turn: 111,
      perspective: 1,
    })

    expect(snapshot?.players).toHaveLength(1)
    expect(snapshot?.players[0]).toMatchObject({
      playerId: 8,
      racePlayer: 'koshling',
      turn: 111,
      status: 'no_exact_solution',
      constraints: { playerId: 8, militaryDelta2x: -107738 },
      actionCatalog: { catalogSize: 9 },
      solver: { solver_status: 'INFEASIBLE' },
    })
  })

  it('falls back to constraints.playerId when playerId is omitted on the row detail', () => {
    const data: TableDataResponse = {
      analyticId: 'scores',
      includeBuildInference: true,
      columns: ['Race (player)', 'Build inference'],
      rows: [['koshling', '']],
      inferenceByRow: [
        {
          displayStatus: 'failure',
          status: 'no_exact_solution',
          summary: 'No feasible build explanation found',
          solutionCount: 0,
          isComplete: true,
          solutions: [],
          diagnostics: {
            turn: 111,
            constraints: { playerId: 8, militaryDelta2x: -107738 },
            actionCatalog: { catalogSize: 9, actions: [] },
            solver: { status: 'no_exact_solution' },
          },
        },
      ],
    }

    const snapshot = scoresDiagnosticsFromTable(data, {
      gameId: '628580',
      turn: 111,
      perspective: 1,
    })

    expect(snapshot?.players[0]?.playerId).toBe(8)
    expect(snapshot?.players[0]?.constraints?.militaryDelta2x).toBe(-107738)
  })
})
