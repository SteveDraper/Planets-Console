import { describe, expect, it } from 'vitest'
import {
  homeworldInactiveHint,
  homeworldBaselineDegradedMessage,
  INACTIVE_REASON_NO_HOMEWORLD,
  INACTIVE_REASON_WANDERING_TRIBES,
} from './constants'
import { homeworldLocatorInactiveReasonFromGameInfo } from './homeworldAvailability'
import { parseHomeworldLocatorPayload } from './wireSchema'
import { resolveHomeworldMarkerDisplays } from './mapAnalytic'

describe('homeworldLocatorInactiveReasonFromGameInfo', () => {
  it('returns null when traditional homeworlds exist', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { nohomeworld: false, wanderingtribescount: 0 },
      })
    ).toBeNull()
  })

  it('detects nohomeworld from settings', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { nohomeworld: true },
      })
    ).toBe(INACTIVE_REASON_NO_HOMEWORLD)
  })

  it('detects wandering tribes from game block', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1, wanderingtribescount: 2 },
        settings: {},
      })
    ).toBe(INACTIVE_REASON_WANDERING_TRIBES)
  })
})

describe('homeworldInactiveHint', () => {
  it('maps known reasons to user-facing hints', () => {
    expect(homeworldInactiveHint(INACTIVE_REASON_NO_HOMEWORLD)).toContain('no homeworld')
    expect(homeworldInactiveHint(INACTIVE_REASON_WANDERING_TRIBES)).toContain('Wandering Tribes')
  })
})

describe('homeworldBaselineDegradedMessage', () => {
  it('includes the baseline turn when present', () => {
    expect(homeworldBaselineDegradedMessage(4)).toContain('using turn 4')
    expect(homeworldBaselineDegradedMessage(4)).toContain('Baseline degraded')
  })

  it('omits the turn clause when turn is null', () => {
    expect(homeworldBaselineDegradedMessage(null)).toBe(
      'Baseline degraded. Definite matches are applied cautiously.'
    )
  })
})

describe('parseHomeworldLocatorPayload', () => {
  it('parses a Core map/table wire payload', () => {
    const parsed = parseHomeworldLocatorPayload({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: true,
      baselineTurn: 5,
      markers: [
        {
          planetId: 10,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
        },
      ],
      rows: [
        {
          planetId: 10,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
        },
      ],
      nodes: [],
      edges: [],
    })
    expect(parsed).not.toBeNull()
    expect(parsed?.baselineDegraded).toBe(true)
    expect(parsed?.markers).toHaveLength(1)
    expect(parsed?.markers?.[0]?.confidenceTier).toBe('definite')
  })

  it('rejects invalid confidence tiers', () => {
    expect(
      parseHomeworldLocatorPayload({
        analyticId: 'homeworld-locator',
        available: true,
        baselineDegraded: false,
        markers: [
          {
            planetId: 1,
            perspective: null,
            confidenceTier: 'maybe',
            attribution: 'inferred',
          },
        ],
      })
    ).toBeNull()
  })
})

describe('resolveHomeworldMarkerDisplays', () => {
  it('binds markers to base-map planet coordinates', () => {
    const displays = resolveHomeworldMarkerDisplays(
      [
        {
          planetId: 7,
          perspective: null,
          confidenceTier: 'possible',
          attribution: 'inferred',
        },
        {
          planetId: 99,
          perspective: 2,
          confidenceTier: 'definite',
          attribution: 'inferred',
        },
      ],
      [
        { id: 'base-map:p7', label: 'p7', x: 100, y: 200, planet: { id: 7 } },
        { id: 'connections:p7', label: 'p7', x: 0, y: 0, planet: { id: 7 } },
      ],
      'base-map'
    )
    expect(displays).toEqual([
      {
        planetId: 7,
        x: 100,
        y: 200,
        confidenceTier: 'possible',
        perspective: null,
        attribution: 'inferred',
      },
    ])
  })
})
