import { describe, it, expect } from 'vitest'
import type { MapHoverContribution } from './mapHoverContributionTypes'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'
import {
  applyReadyAsyncBlocks,
  findPendingAsyncHover,
  omitPendingAsyncContributions,
} from './resolveMapHoverAsync'

function asyncContribution(requestKey: string): MapHoverContribution {
  return {
    id: `cartography:${requestKey}`,
    role: 'cartography',
    kind: 'descriptive',
    title: 'Stellar Cartography',
    placement: { mode: 'cursor' },
    blocks: [{ type: 'async', requestKey, status: 'pending' }],
  }
}

describe('resolveMapHoverAsync', () => {
  it('finds pending async hover and its fetch owner', () => {
    const contributor: MapInteractionContributor = {
      id: 'cartography',
      role: 'cartography',
      hitTest: () => null,
      fetch: async () => [{ type: 'lines', lines: ['ok'] }],
    }
    const pending = findPendingAsyncHover(
      [asyncContribution('10:20')],
      [contributor]
    )
    expect(pending?.requestKey).toBe('10:20')
    expect(pending?.contributor).toBe(contributor)
  })

  it('applies ready blocks and drops empty samples', () => {
    const raw = [asyncContribution('1:2')]
    expect(
      applyReadyAsyncBlocks(raw, '1:2', [{ type: 'lines', lines: ['nebula'] }])
    ).toEqual([
      {
        ...raw[0],
        blocks: [{ type: 'lines', lines: ['nebula'] }],
      },
    ])
    expect(applyReadyAsyncBlocks(raw, '1:2', [])).toEqual([])
  })

  it('omits unresolved async contributions from chrome', () => {
    expect(omitPendingAsyncContributions([asyncContribution('3:4')])).toEqual([])
    expect(
      omitPendingAsyncContributions([
        {
          id: 'region',
          role: 'region',
          kind: 'descriptive',
          title: 'Region',
          placement: { mode: 'cursor' },
          blocks: [{ type: 'lines', lines: ['sector'] }],
        },
      ])
    ).toHaveLength(1)
  })
})
