import { describe, expect, it } from 'vitest'
import { BLACK_HOLE_CONCEPT_CONSTANTS } from './blackHoleConceptConstants'
import { loadBlackHoleErgosphereContractFixture } from './loadBlackHoleErgosphereContractFixture'

describe('BLACK_HOLE_CONCEPT_CONSTANTS', () => {
  it('matches test-fixtures/black-hole-ergosphere-contract.json', () => {
    const contract = loadBlackHoleErgosphereContractFixture()
    expect(BLACK_HOLE_CONCEPT_CONSTANTS.ergosphereBandCount).toBe(contract.ergosphereBandCount)
    expect(BLACK_HOLE_CONCEPT_CONSTANTS.haloExtraLy).toBe(contract.haloExtraLy)
  })
})
