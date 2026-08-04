import { describe, expect, it, vi } from 'vitest'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
  homeworldBaselineDegradedMessage,
  INACTIVE_REASON_NO_HOMEWORLD,
  INACTIVE_REASON_SCENARIO_OVERRIDE,
  INACTIVE_REASON_WANDERING_TRIBES,
} from './constants'
import {
  homeworldLocatorInactiveReasonFromGameInfo,
  withoutInactiveHomeworldLocator,
} from './homeworldAvailability'
import { parseHomeworldLocatorPayload } from './wireSchema'
import {
  fetchHomeworldLocatorMapDataResponse,
  resolveHomeworldMarkerDisplays,
} from './mapAnalytic'
import * as homeworldApi from './api'


describe('homeworldLocatorInactiveReasonFromGameInfo', () => {
  it('returns null when traditional homeworlds exist', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: {
          nohomeworld: false,
          wanderingtribescount: 0,
          hwdistribution: 2,
          extraplanets: 0,
        },
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

  it('detects Ashes via hwdistribution One vs. Circle', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { hwdistribution: 4 },
      })
    ).toBe(INACTIVE_REASON_SCENARIO_OVERRIDE)
  })

  it('detects Crazy Intermix via extraplanets + random loc', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { extraplanets: 3, extraplanetsrandomloc: true },
      })
    ).toBe(INACTIVE_REASON_SCENARIO_OVERRIDE)
  })

  it('detects Disunited Kingdoms via extraplanets without random loc', () => {
    expect(
      homeworldLocatorInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { extraplanets: 3, extraplanetsrandomloc: false },
      })
    ).toBe(INACTIVE_REASON_SCENARIO_OVERRIDE)
  })
})

describe('homeworldInactiveHint', () => {
  it('maps known reasons to user-facing hints', () => {
    expect(homeworldInactiveHint(INACTIVE_REASON_NO_HOMEWORLD)).toContain('no homeworld')
    expect(homeworldInactiveHint(INACTIVE_REASON_WANDERING_TRIBES)).toContain('Wandering Tribes')
    expect(homeworldInactiveHint(INACTIVE_REASON_SCENARIO_OVERRIDE)).toContain('Ashes')
    expect(homeworldInactiveHint(INACTIVE_REASON_SCENARIO_OVERRIDE)).toContain('Crazy Intermix')
    expect(homeworldInactiveHint(INACTIVE_REASON_SCENARIO_OVERRIDE)).toContain(
      'Disunited Kingdoms'
    )
  })
})

describe('withoutInactiveHomeworldLocator', () => {
  it('keeps homeworld-locator when available', () => {
    expect(
      withoutInactiveHomeworldLocator(
        ['scores', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'fleet'],
        null
      )
    ).toEqual(['scores', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'fleet'])
  })

  it('drops homeworld-locator from effective enabled ids when inactive', () => {
    expect(
      withoutInactiveHomeworldLocator(
        ['scores', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'fleet'],
        INACTIVE_REASON_NO_HOMEWORLD
      )
    ).toEqual(['scores', 'fleet'])
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
      regionOverlays: [
        {
          kind: 'homeworld-sector',
          id: 'homeworld-sector-0',
          fillColor: '#f97316',
          fillOpacity: 0.2,
          isPinned: false,
          candidateCount: 2,
          geometry: {
            type: 'boundary',
            vertices: [
              { x: 1, y: 0 },
              { x: 0, y: 1 },
              { x: 0, y: 0.5 },
              { x: 0.5, y: 0 },
            ],
            edges: [
              { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
              { type: 'line' },
              { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
              { type: 'line' },
            ],
          },
        },
      ],
    })
    expect(parsed).not.toBeNull()
    expect(parsed?.baselineDegraded).toBe(true)
    expect(parsed?.markers).toHaveLength(1)
    expect(parsed?.markers?.[0]?.confidenceTier).toBe('definite')
    expect(parsed?.markers?.[0]?.isMostProbable).toBe(false)
    expect(parsed?.regionOverlays).toHaveLength(1)
  })

  it('defaults isMostProbable, assertedCue, and locationAsserted when omitted', () => {
    const parsed = parseHomeworldLocatorPayload({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [
        {
          planetId: 10,
          perspective: null,
          confidenceTier: 'possible',
          attribution: 'inferred',
        },
      ],
    })
    expect(parsed?.rows?.[0]?.isMostProbable).toBe(false)
    expect(parsed?.rows?.[0]?.assertedCue).toBe(false)
    expect(parsed?.rows?.[0]?.locationAsserted).toBe(false)
  })

  it('parses assertedCue and locationAsserted from the wire', () => {
    const parsed = parseHomeworldLocatorPayload({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      markers: [
        {
          planetId: 10,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'user_asserted',
          assertedCue: true,
          locationAsserted: true,
        },
      ],
      rows: [
        {
          planetId: 10,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'user_asserted',
          assertedCue: true,
          locationAsserted: false,
        },
      ],
    })
    expect(parsed?.markers?.[0]?.assertedCue).toBe(true)
    expect(parsed?.markers?.[0]?.locationAsserted).toBe(true)
    expect(parsed?.rows?.[0]?.assertedCue).toBe(true)
    expect(parsed?.rows?.[0]?.locationAsserted).toBe(false)
  })

  it('accepts isMostProbable on candidate rows and markers', () => {
    const parsed = parseHomeworldLocatorPayload({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      markers: [
        {
          planetId: 22,
          perspective: 3,
          confidenceTier: 'possible',
          attribution: 'inferred',
          assertedCue: false,
          isMostProbable: true,
        },
      ],
      rows: [
        {
          planetId: 22,
          perspective: 3,
          confidenceTier: 'possible',
          attribution: 'inferred',
          assertedCue: false,
          isMostProbable: true,
        },
      ],
    })
    expect(parsed?.markers?.[0]?.isMostProbable).toBe(true)
    expect(parsed?.rows?.[0]?.isMostProbable).toBe(true)
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
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: false,
        },
        {
          planetId: 99,
          perspective: 2,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: true,
          isMostProbable: false,
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
        assertedCue: false,
        locationAsserted: false,
        isMostProbable: false,
      },
    ])
  })

  it('passes through isMostProbable when set on the wire marker', () => {
    const displays = resolveHomeworldMarkerDisplays(
      [
        {
          planetId: 7,
          perspective: 2,
          confidenceTier: 'possible',
          attribution: 'inferred',
          assertedCue: false,
          isMostProbable: true,
        },
      ],
      [{ id: 'base-map:p7', label: 'p7', x: 50, y: 60, planet: { id: 7 } }],
      'base-map'
    )
    expect(displays[0]?.isMostProbable).toBe(true)
  })
})

describe('fetchHomeworldLocatorMapDataResponse', () => {
  it('keeps homeworldMarkers on the shared map cache payload (panel must not strip them)', async () => {
    vi.spyOn(homeworldApi, 'fetchHomeworldLocatorMap').mockResolvedValue({
      analyticId: HOMEWORLD_LOCATOR_ANALYTIC_ID,
      available: true,
      baselineDegraded: false,
      markers: [
        {
          planetId: 7,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          isMostProbable: false,
        },
      ],
      regionOverlays: [
        {
          kind: 'homeworld-sector',
          id: 'homeworld-sector-0',
          fillColor: '#f97316',
          fillOpacity: 0,
          geometry: {
            type: 'boundary',
            vertices: [
              { x: 0, y: 0 },
              { x: 1, y: 0 },
              { x: 1, y: 1 },
              { x: 0, y: 1 },
            ],
            edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
          },
        },
      ],
    })

    const data = await fetchHomeworldLocatorMapDataResponse({
      gameId: '680224',
      turn: 20,
      perspective: 2,
    })

    expect(data.homeworldMarkers).toHaveLength(1)
    expect(data.homeworldMarkers?.[0]?.planetId).toBe(7)
    expect(data.regionOverlays).toHaveLength(1)
    vi.restoreAllMocks()
  })
})
