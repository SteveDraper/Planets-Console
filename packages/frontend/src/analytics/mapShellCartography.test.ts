import { describe, expect, it } from 'vitest'
import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from './mapAnalyticIds'
import { isStellarCartographyMapEnabled } from './mapShellCartography'

describe('isStellarCartographyMapEnabled', () => {
  it('is true when stellar cartography is in enabled map ids', () => {
    expect(isStellarCartographyMapEnabled(['connections', STELLAR_CARTOGRAPHY_ANALYTIC_ID])).toBe(
      true
    )
  })

  it('is false when stellar cartography is not enabled', () => {
    expect(isStellarCartographyMapEnabled(['connections'])).toBe(false)
  })
})
