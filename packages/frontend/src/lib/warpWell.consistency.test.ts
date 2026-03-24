/**
 * Golden vectors from repo ``test-fixtures/warp-well-consistency.json`` --
 * must match ``packages/api/tests/test_warp_well_consistency.py``.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { isCoordinateInWarpWell, mapCellsInWarpWell, type WarpWellType } from './warpWell'

const __dirname = dirname(fileURLToPath(import.meta.url))
const fixturePath = join(__dirname, '../../../../test-fixtures/warp-well-consistency.json')

type CoordinateCase = {
  planetX: number
  planetY: number
  debrisdisk: number
  queryX: number
  queryY: number
  wellType: WarpWellType
  inside: boolean
}

type CellCase = {
  planetX: number
  planetY: number
  debrisdisk: number
  wellType: WarpWellType
  cells: number[][]
}

function sortedCellPairs(cells: { gx: number; gy: number }[]): number[][] {
  return [...cells]
    .sort((a, b) => a.gx - b.gx || a.gy - b.gy)
    .map(({ gx, gy }) => [gx, gy])
}

describe('warpWell consistency fixture', () => {
  const raw = readFileSync(fixturePath, 'utf8')
  const fixture = JSON.parse(raw) as {
    coordinateCases: CoordinateCase[]
    cellCases: CellCase[]
  }

  it('coordinate cases match golden expectations', () => {
    for (const c of fixture.coordinateCases) {
      const planet = { debrisdisk: c.debrisdisk }
      expect(
        isCoordinateInWarpWell(
          c.planetX,
          c.planetY,
          planet,
          c.queryX,
          c.queryY,
          c.wellType
        )
      ).toBe(c.inside)
    }
  })

  it('cell cases match golden expectations', () => {
    for (const c of fixture.cellCases) {
      const planet = { debrisdisk: c.debrisdisk }
      const got = sortedCellPairs(
        mapCellsInWarpWell(c.planetX, c.planetY, c.wellType, planet)
      )
      expect(got).toEqual(c.cells)
    }
  })
})
