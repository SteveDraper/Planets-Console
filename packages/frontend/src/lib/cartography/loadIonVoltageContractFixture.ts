import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Repo-root contract shared with packages/api/tests (test-fixtures/ion_voltage_contract.json). */
export function loadIonVoltageContractFixture(): {
  description: string
  tolerance: number
  gridTolerance: number
  cases: Array<{
    id: string
    cloudy: boolean
    circles: Array<{ x: number; y: number; radius: number; voltage: number }>
    bounds: { minX: number; minY: number; maxX: number; maxY: number }
    gridStep: number
    storms?: Array<Record<string, unknown>>
    samples: Array<{
      x: number
      y: number
      expectedVoltage: number
      expectedClass?: number
    }>
  }>
} {
  const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '../../../../../')
  const raw = readFileSync(join(repoRoot, 'test-fixtures/ion_voltage_contract.json'), 'utf8')
  return JSON.parse(raw) as ReturnType<typeof loadIonVoltageContractFixture>
}
