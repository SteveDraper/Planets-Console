import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Repo-root contract shared with packages/api/tests (test-fixtures/black-hole-ergosphere-contract.json). */
export function loadBlackHoleErgosphereContractFixture(): {
  description: string
  ergosphereBandCount: number
  haloExtraLy: number
  cases: Array<{
    id: string
    coreradius: number
    bandradius: number
    outerRadiusLy: number
    haloRadiusLy: number
    samples: Array<{
      dist: number
      band: number | null
      maxWarp: number | null
      fuelSavingPercent: number | null
    }>
  }>
} {
  const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '../../../../../')
  const raw = readFileSync(
    join(repoRoot, 'test-fixtures/black-hole-ergosphere-contract.json'),
    'utf8'
  )
  return JSON.parse(raw) as ReturnType<typeof loadBlackHoleErgosphereContractFixture>
}
