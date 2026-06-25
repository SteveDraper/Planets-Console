import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Repo-root golden vectors shared with packages/bff/tests (test-fixtures/fleet-table-wire.json). */
export type FleetTableWireGoldenCase = {
  name: string
  coreInput: unknown
  expectedTableWire: unknown
  /** When false, case documents BFF sparse wire only; skip Zod parse tests. */
  zodParseable?: boolean
}

export function loadFleetTableWireFixture(): {
  description: string
  cases: FleetTableWireGoldenCase[]
} {
  const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '../../../../../')
  const raw = readFileSync(join(repoRoot, 'test-fixtures/fleet-table-wire.json'), 'utf8')
  return JSON.parse(raw) as ReturnType<typeof loadFleetTableWireFixture>
}

export function zodParseableFleetTableWireCases(
  cases: FleetTableWireGoldenCase[]
): FleetTableWireGoldenCase[] {
  return cases.filter((caseEntry) => caseEntry.zodParseable !== false)
}
