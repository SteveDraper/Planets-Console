import { describe, expect, it } from 'vitest'
import {
  blackHoleErgosphereBandGrey,
  ionStormFillOpacity,
  ionStormStrokeColor,
  starClusterBandEdgeOpacity,
  starClusterBandPeakOpacity,
  starClusterColorFromTemp,
  starClusterCoreEdgeOpacity,
  starClusterCoreHotspotOpacity,
  STAR_CLUSTER_BAND_MAX_OPACITY,
  STAR_CLUSTER_CORE_FILL_ALPHA,
  starClusterHaloRadiusLy,
  starClusterPeakRadiationAtCoreEdge,
} from './stellarCartographyTheme'

function parseHexRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

describe('stellarCartographyTheme', () => {
  it('ramps black hole ergosphere greys from inner to outer band', () => {
    expect(blackHoleErgosphereBandGrey(1)).toBe('#1a1a1a')
    expect(blackHoleErgosphereBandGrey(9)).toBe('#4a4a4a')
    expect(parseHexRgb(blackHoleErgosphereBandGrey(5))[0]).toBeGreaterThan(
      parseHexRgb(blackHoleErgosphereBandGrey(2))[0]
    )
  })

  it('uses warmer stroke colors for classes 4 and 5', () => {
    expect(ionStormStrokeColor(3)).toBe('#eab308')
    expect(ionStormStrokeColor(4)).toBe('#f97316')
    expect(ionStormStrokeColor(5)).toBe('#ef4444')
  })

  it('scales fill opacity by class', () => {
    expect(ionStormFillOpacity(1)).toBe(0.15)
    expect(ionStormFillOpacity(3)).toBe(0.45)
    expect(ionStormFillOpacity(5)).toBe(0.75)
  })

  it('derives star cluster halo radius from mass', () => {
    expect(starClusterHaloRadiusLy(6256)).toBeCloseTo(79.1, 1)
  })

  it('maps hotter stars to stronger radiation band opacity', () => {
    const hot = starClusterBandPeakOpacity(28601, 42, starClusterHaloRadiusLy(6256))
    const cool = starClusterBandPeakOpacity(1359, 49, starClusterHaloRadiusLy(7278))
    expect(hot).toBeGreaterThan(cool)
    expect(starClusterPeakRadiationAtCoreEdge(28601, 42, starClusterHaloRadiusLy(6256))).toBeGreaterThan(
      100
    )
  })

  it('keeps lethal core hotspot brighter than the radiation band', () => {
    const haloRadius = starClusterHaloRadiusLy(6256)
    const bandPeak = starClusterBandPeakOpacity(28601, 42, haloRadius)
    expect(starClusterCoreHotspotOpacity()).toBeGreaterThan(bandPeak)
    expect(starClusterCoreHotspotOpacity()).toBeGreaterThan(starClusterCoreEdgeOpacity())
    expect(starClusterBandEdgeOpacity()).toBeGreaterThan(0)
    expect(bandPeak).toBeGreaterThan(starClusterBandEdgeOpacity())
    expect(STAR_CLUSTER_BAND_MAX_OPACITY).toBeCloseTo(0.5 * (0.5 / 0.88), 5)
    expect(STAR_CLUSTER_CORE_FILL_ALPHA).toBe(0.5)
  })

  it('anchors star cluster color at 10000 red and 50000 white', () => {
    expect(starClusterColorFromTemp(10_000)).toBe('#dc2626')
    expect(starClusterColorFromTemp(50_000)).toBe('#f8fafc')

    const at10k = parseHexRgb(starClusterColorFromTemp(10_000))
    const at28k = parseHexRgb(starClusterColorFromTemp(28_601))
    const at50k = parseHexRgb(starClusterColorFromTemp(50_000))

    expect(at10k[0]).toBeGreaterThan(at10k[1])
    expect(at10k[0]).toBeGreaterThan(at10k[2])
    expect(at50k[0] + at50k[1] + at50k[2]).toBeGreaterThan(at10k[0] + at10k[1] + at10k[2])
    expect(at28k[1]).toBeGreaterThan(at10k[1])
    expect(at28k[1]).toBeLessThan(at50k[1])
    expect(at28k[2]).toBeLessThan(at50k[2])
  })
})
