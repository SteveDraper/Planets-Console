import { describe, it, expect, vi } from 'vitest'
import { collectMapHoverContributions } from './collectMapHoverContributions'
import type { MapHoverContribution } from './mapHoverContributionTypes'
import type {
  MapHitContext,
  MapInteractionContributor,
} from './mapInteractionContributorTypes'

function contribution(
  partial: Pick<MapHoverContribution, 'id' | 'role'> &
    Partial<Omit<MapHoverContribution, 'id' | 'role'>>
): MapHoverContribution {
  return {
    kind: 'descriptive',
    title: partial.role,
    placement: { mode: 'cursor' },
    blocks: [{ type: 'lines', lines: [partial.id] }],
    ...partial,
  }
}

const hit: MapHitContext = {
  clientPos: { x: 10, y: 20 },
  hitEpoch: 1,
  domNode: null,
  transform: undefined,
}

describe('collectMapHoverContributions', () => {
  it('collects hitTest results when a pointer hit is present', () => {
    const fleet = contribution({ id: 'fleet:1', role: 'fleet' })
    const contributors: MapInteractionContributor[] = [
      {
        id: 'fleet',
        role: 'fleet',
        hitTest: () => fleet,
      },
      {
        id: 'region',
        role: 'region',
        hitTest: () => null,
      },
    ]
    expect(collectMapHoverContributions(contributors, hit)).toEqual([fleet])
  })

  it('uses stickyContribution when hit is null', () => {
    const pinned = contribution({
      id: 'planet:7',
      role: 'planet',
      placement: { mode: 'anchor', flowX: 1, flowY: 2, pinned: true },
    })
    const contributors: MapInteractionContributor[] = [
      {
        id: 'planet',
        role: 'planet',
        hitTest: () => {
          throw new Error('hitTest must not run without a pointer hit')
        },
        stickyContribution: () => pinned,
      },
      {
        id: 'fleet',
        role: 'fleet',
        hitTest: () => null,
      },
    ]
    expect(collectMapHoverContributions(contributors, null)).toEqual([pinned])
  })

  it('falls back to sticky when hitTest returns null under a live pointer', () => {
    const pinned = contribution({
      id: 'planet:3',
      role: 'planet',
      placement: { mode: 'anchor', flowX: 0, flowY: 0, pinned: true },
    })
    const contributors: MapInteractionContributor[] = [
      {
        id: 'planet',
        role: 'planet',
        hitTest: () => null,
        stickyContribution: () => pinned,
      },
    ]
    expect(collectMapHoverContributions(contributors, hit)).toEqual([pinned])
  })

  it('does not duplicate sticky when hitTest already returned for that contributor', () => {
    const fromHit = contribution({ id: 'planet:1', role: 'planet' })
    const stickyFn = vi.fn(() =>
      contribution({
        id: 'planet:1',
        role: 'planet',
        placement: { mode: 'anchor', flowX: 0, flowY: 0, pinned: true },
      })
    )
    const contributors: MapInteractionContributor[] = [
      {
        id: 'planet',
        role: 'planet',
        hitTest: () => fromHit,
        stickyContribution: stickyFn,
      },
    ]
    expect(collectMapHoverContributions(contributors, hit)).toEqual([fromHit])
    expect(stickyFn).not.toHaveBeenCalled()
  })

  it('unions sticky planet with pointer fleet without role special-casing', () => {
    const pinned = contribution({
      id: 'planet:9',
      role: 'planet',
      placement: { mode: 'anchor', flowX: 5, flowY: 6, pinned: true },
    })
    const fleet = contribution({ id: 'fleet:2', role: 'fleet' })
    const contributors: MapInteractionContributor[] = [
      {
        id: 'planet',
        role: 'planet',
        hitTest: () => null,
        stickyContribution: () => pinned,
      },
      {
        id: 'fleet',
        role: 'fleet',
        hitTest: () => fleet,
      },
    ]
    expect(collectMapHoverContributions(contributors, hit)).toEqual([
      pinned,
      fleet,
    ])
  })
})
