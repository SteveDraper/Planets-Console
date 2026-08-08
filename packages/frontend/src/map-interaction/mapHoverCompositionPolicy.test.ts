import { describe, it, expect } from 'vitest'
import type { MapHoverContribution } from './mapHoverContributionTypes'
import {
  composeMapHoverContributions,
  resolveDescriptiveHostPlacement,
} from './mapHoverCompositionPolicy'

function contribution(
  partial: Partial<MapHoverContribution> &
    Pick<MapHoverContribution, 'id' | 'role' | 'kind' | 'title'>
): MapHoverContribution {
  return {
    placement: { mode: 'cursor' },
    blocks: [{ type: 'lines', lines: [partial.title] }],
    ...partial,
  }
}

describe('composeMapHoverContributions', () => {
  it('fleet mergesWith planet into one anchored host (planet then fleet sections)', () => {
    const planet = contribution({
      id: 'planet:1',
      role: 'planet',
      kind: 'descriptive',
      title: 'Planet',
      placement: { mode: 'anchor', flowX: 10, flowY: 20 },
    })
    const fleet = contribution({
      id: 'fleet:1',
      role: 'fleet',
      kind: 'descriptive',
      title: 'Fleet',
      placement: { mode: 'cursor' },
    })

    const result = composeMapHoverContributions([planet, fleet])

    expect(result.suppressedIds).toEqual([])
    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.placement).toEqual({
      mode: 'anchor',
      flowX: 10,
      flowY: 20,
    })
    expect(result.descriptiveHosts[0]!.sections.map((s) => s.role)).toEqual([
      'planet',
      'fleet',
    ])
    expect(result.stacked).toEqual([])
  })

  it('region and cartography yieldTo planet descriptive', () => {
    const planet = contribution({
      id: 'planet:1',
      role: 'planet',
      kind: 'descriptive',
      title: 'Planet',
      placement: { mode: 'anchor', flowX: 0, flowY: 0 },
    })
    const region = contribution({
      id: 'region:1',
      role: 'region',
      kind: 'descriptive',
      title: 'Region',
    })
    const cartography = contribution({
      id: 'cartography:1',
      role: 'cartography',
      kind: 'descriptive',
      title: 'Cartography',
    })

    const result = composeMapHoverContributions([planet, region, cartography])

    expect(result.suppressedIds).toEqual(
      expect.arrayContaining(['region:1', 'cartography:1'])
    )
    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.sections.map((s) => s.role)).toEqual([
      'planet',
    ])
  })

  it('wormhole map-element stacks with planet descriptive (not suppressed)', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'planet:1',
        role: 'planet',
        kind: 'descriptive',
        title: 'Planet',
        placement: { mode: 'anchor', flowX: 1, flowY: 2 },
      }),
      contribution({
        id: 'wormhole:1',
        role: 'wormhole',
        kind: 'map-element',
        title: 'Wormhole',
      }),
    ])

    expect(result.suppressedIds).toEqual([])
    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.sections.map((s) => s.role)).toEqual([
      'planet',
    ])
    expect(result.stacked.map((c) => c.id)).toEqual(['wormhole:1'])
  })

  it('region mergesWith cartography as titled cursor sections in role order', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'cartography:1',
        role: 'cartography',
        kind: 'descriptive',
        title: 'Stellar Cartography',
      }),
      contribution({
        id: 'region:1',
        role: 'region',
        kind: 'descriptive',
        title: 'Visibility',
      }),
    ])

    expect(result.suppressedIds).toEqual([])
    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.placement).toEqual({ mode: 'cursor' })
    expect(
      result.descriptiveHosts[0]!.sections.map((s) => ({
        role: s.role,
        title: s.title,
      }))
    ).toEqual([
      { role: 'region', title: 'Visibility' },
      { role: 'cartography', title: 'Stellar Cartography' },
    ])
  })

  it('cartography descriptive and wormhole map-element show simultaneously', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'cartography:1',
        role: 'cartography',
        kind: 'descriptive',
        title: 'Stellar Cartography',
      }),
      contribution({
        id: 'wormhole:endpoint:10,20',
        role: 'wormhole',
        kind: 'map-element',
        title: 'Wormhole',
      }),
    ])

    expect(result.suppressedIds).toEqual([])
    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.sections.map((s) => s.role)).toEqual([
      'cartography',
    ])
    expect(result.stacked).toHaveLength(1)
    expect(result.stacked[0]!.id).toBe('wormhole:endpoint:10,20')
    expect(result.stacked[0]!.kind).toBe('map-element')
  })

  it('deep-space fleet alone stays a separate descriptive host', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'fleet:1',
        role: 'fleet',
        kind: 'descriptive',
        title: 'Fleet',
        placement: { mode: 'anchor', flowX: 5, flowY: 6 },
      }),
    ])

    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.descriptiveHosts[0]!.sections.map((s) => s.role)).toEqual([
      'fleet',
    ])
    expect(result.descriptiveHosts[0]!.placement).toEqual({
      mode: 'anchor',
      flowX: 5,
      flowY: 6,
    })
  })

  it('fleet and region without merge edge produce two descriptive hosts', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'fleet:1',
        role: 'fleet',
        kind: 'descriptive',
        title: 'Fleet',
      }),
      contribution({
        id: 'region:1',
        role: 'region',
        kind: 'descriptive',
        title: 'Region',
      }),
    ])

    expect(result.descriptiveHosts).toHaveLength(2)
    expect(result.descriptiveHosts.map((h) => h.sections[0]!.role)).toEqual([
      'fleet',
      'region',
    ])
  })

  it('map-element contributions stack independently of descriptive host', () => {
    const result = composeMapHoverContributions([
      contribution({
        id: 'planet:1',
        role: 'planet',
        kind: 'descriptive',
        title: 'Planet',
        placement: { mode: 'anchor', flowX: 0, flowY: 0 },
      }),
      contribution({
        id: 'wormhole-affordance:1',
        role: 'wormhole',
        kind: 'map-element',
        title: 'Wormhole marker',
      }),
    ])

    expect(result.descriptiveHosts).toHaveLength(1)
    expect(result.stacked).toHaveLength(1)
    expect(result.stacked[0]!.id).toBe('wormhole-affordance:1')
    expect(result.suppressedIds).toEqual([])
  })
})

describe('resolveDescriptiveHostPlacement', () => {
  it('prefers pinned anchor over other anchors', () => {
    const placement = resolveDescriptiveHostPlacement([
      contribution({
        id: 'planet:1',
        role: 'planet',
        kind: 'descriptive',
        title: 'Planet',
        placement: { mode: 'anchor', flowX: 1, flowY: 1 },
      }),
      contribution({
        id: 'planet:pin',
        role: 'planet',
        kind: 'descriptive',
        title: 'Pinned',
        placement: { mode: 'anchor', flowX: 9, flowY: 9, pinned: true },
      }),
    ])
    expect(placement).toEqual({
      mode: 'anchor',
      flowX: 9,
      flowY: 9,
      pinned: true,
    })
  })

  it('returns cursor when no contribution requests anchor', () => {
    expect(
      resolveDescriptiveHostPlacement([
        contribution({
          id: 'region:1',
          role: 'region',
          kind: 'descriptive',
          title: 'Region',
        }),
      ])
    ).toEqual({ mode: 'cursor' })
  })
})
