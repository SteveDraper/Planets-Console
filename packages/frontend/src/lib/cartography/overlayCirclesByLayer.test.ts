import { describe, expect, it } from 'vitest'
import type { StellarCartographyOverlayCircle } from '../../api/bff'
import {
  groupOverlayCirclesByLayer,
  vectorOverlayCirclesInPaintOrder,
} from './overlayCirclesByLayer'

function circle(
  layer: StellarCartographyOverlayCircle['layer'],
  id: string
): StellarCartographyOverlayCircle {
  const base = { id, x: 1, y: 2, radius: 3 }
  switch (layer) {
    case 'debris-disks':
      return { ...base, layer: 'debris-disks' }
    case 'nebulae':
      return { ...base, layer: 'nebulae' }
    case 'ion-storms':
      return { ...base, layer: 'ion-storms', voltage: 1, class: 1 }
    case 'star-clusters':
      return { ...base, layer: 'star-clusters' }
    case 'neutron-clusters':
      return { ...base, layer: 'neutron-clusters' }
    case 'black-holes':
      return { ...base, layer: 'black-holes', coreRadius: 1, bandRadius: 1 }
  }
}

describe('groupOverlayCirclesByLayer', () => {
  it('partitions each layer into one bucket', () => {
    const grouped = groupOverlayCirclesByLayer([
      circle('nebulae', 'n1'),
      circle('black-holes', 'bh1'),
      circle('ion-storms', 'i1'),
      circle('star-clusters', 'sc1'),
      circle('neutron-clusters', 'nc1'),
      circle('debris-disks', 'd1'),
    ])
    expect(grouped.nebulae.map((c) => c.id)).toEqual(['n1'])
    expect(grouped.blackHoles.map((c) => c.id)).toEqual(['bh1'])
    expect(grouped.ionStorms.map((c) => c.id)).toEqual(['i1'])
    expect(grouped.starClusters.map((c) => c.id)).toEqual(['sc1'])
    expect(grouped.neutronClusters.map((c) => c.id)).toEqual(['nc1'])
    expect(grouped.debrisDisks.map((c) => c.id)).toEqual(['d1'])
  })
})

describe('vectorOverlayCirclesInPaintOrder', () => {
  it('returns star clusters before black holes', () => {
    const byLayer = groupOverlayCirclesByLayer([
      circle('black-holes', 'bh'),
      circle('star-clusters', 'sc'),
    ])
    expect(vectorOverlayCirclesInPaintOrder(byLayer).map((c) => c.id)).toEqual(['sc', 'bh'])
  })
})
