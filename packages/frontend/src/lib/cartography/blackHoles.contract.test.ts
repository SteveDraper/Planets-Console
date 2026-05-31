import { describe, expect, it } from 'vitest'
import {
  blackHoleBandAt,
  blackHoleBandRadiiLy,
  blackHoleFuelSavingPercentAt,
  blackHoleMaxWarpAt,
  blackHoleErgosphereOuterLy,
  blackHoleHaloRadiusLy,
  ERGOSPHERE_BAND_COUNT,
} from './blackHoles'
import { loadBlackHoleErgosphereContractFixture } from './loadBlackHoleErgosphereContractFixture'

/** Host-aligned golden vectors; single source at test-fixtures/black-hole-ergosphere-contract.json */
describe('black hole ergosphere contract fixture', () => {
  const contractFixture = loadBlackHoleErgosphereContractFixture()

  it('matches fixture constants and geometry radii', () => {
    expect(ERGOSPHERE_BAND_COUNT).toBe(contractFixture.ergosphereBandCount)
    for (const testCase of contractFixture.cases) {
      expect(blackHoleErgosphereOuterLy(testCase.coreradius, testCase.bandradius)).toBe(
        testCase.outerRadiusLy
      )
      expect(blackHoleHaloRadiusLy(testCase.coreradius, testCase.bandradius)).toBe(
        testCase.haloRadiusLy
      )
    }
  })

  it('matches band, max warp, and fuel saving at fixture distances', () => {
    for (const testCase of contractFixture.cases) {
      const { coreradius, bandradius } = testCase
      for (const sample of testCase.samples) {
        expect(blackHoleBandAt(coreradius, bandradius, sample.dist)).toBe(sample.band)
        expect(blackHoleMaxWarpAt(coreradius, bandradius, sample.dist)).toBe(sample.maxWarp)
        expect(blackHoleFuelSavingPercentAt(coreradius, bandradius, sample.dist)).toBe(
          sample.fuelSavingPercent
        )
      }
    }
  })

  it('aligns overlay annulus edges with band radii for solace-shaped case', () => {
    const testCase = contractFixture.cases.find((c) => c.id === 'solace-shaped')
    expect(testCase).toBeDefined()
    const { coreradius, bandradius } = testCase!
    for (let band = 1; band <= ERGOSPHERE_BAND_COUNT; band++) {
      const { innerLy, outerLy } = blackHoleBandRadiiLy(coreradius, bandradius, band)
      expect(blackHoleBandAt(coreradius, bandradius, innerLy + 0.001)).toBe(band)
      expect(blackHoleBandAt(coreradius, bandradius, outerLy)).toBe(band)
    }
  })
})
