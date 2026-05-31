import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  fetchGames,
  INCLUDE_DIAGNOSTICS_SESSION_KEY,
  isBffNotFoundError,
  isGenericServerErrorMessage,
  normalizeMapDataResponse,
  toFetchRejectionError,
  withEndpointIfGeneric,
} from './bff'

describe('withEndpointIfGeneric', () => {
  it('appends endpoint for Internal Server Error', () => {
    expect(
      withEndpointIfGeneric('Internal Server Error', 'POST /bff/games/1/info')
    ).toBe('Internal Server Error (POST /bff/games/1/info)')
  })

  it('does not append for specific API messages', () => {
    expect(
      withEndpointIfGeneric('Login credentials are required.', 'POST /bff/games/1/info')
    ).toBe('Login credentials are required.')
  })

  it('appends for bare 500 status message', () => {
    expect(withEndpointIfGeneric('500', 'GET /bff/games')).toBe('500 (GET /bff/games)')
  })

  it('does not append for 404', () => {
    expect(withEndpointIfGeneric('404', 'GET /bff/games')).toBe('404')
  })

  it('does not duplicate endpoint if already present', () => {
    expect(
      withEndpointIfGeneric('500 (GET /bff/games)', 'GET /bff/games')
    ).toBe('500 (GET /bff/games)')
  })
})

describe('isBffNotFoundError', () => {
  it('returns true for leading 404 status in message', () => {
    expect(isBffNotFoundError(new Error('404'))).toBe(true)
    expect(isBffNotFoundError(new Error('404 (GET /bff/games/1/info)'))).toBe(true)
  })

  it('returns true for Core store not-found detail text', () => {
    expect(isBffNotFoundError(new Error("Document not found: 'games/1/info'"))).toBe(true)
    expect(isBffNotFoundError(new Error("Path does not exist: 'games/1/info'"))).toBe(true)
  })

  it('returns false for server and network failures', () => {
    expect(isBffNotFoundError(new Error('Internal Server Error (GET /bff/games/1/info)'))).toBe(
      false
    )
    expect(
      isBffNotFoundError(
        new Error('TypeError: Failed to fetch — GET /bff/games/1/info (request: /bff/games/1/info).')
      )
    ).toBe(false)
  })
})

describe('isGenericServerErrorMessage', () => {
  it('treats empty as generic', () => {
    expect(isGenericServerErrorMessage('')).toBe(true)
  })
})

describe('toFetchRejectionError', () => {
  it('includes endpoint and request path', () => {
    const e = toFetchRejectionError(
      new TypeError('Failed to fetch'),
      'GET /bff/games/1/info',
      '/bff/games/1/info'
    )
    expect(e.message).toContain('GET /bff/games/1/info')
    expect(e.message).toContain('request: /bff/games/1/info')
    expect(e.message).toContain('Failed to fetch')
    expect(e.message).toContain('No HTTP response')
  })

  it('appends Error.cause when present', () => {
    const inner = new Error('connection reset')
    const e = toFetchRejectionError(
      Object.assign(new TypeError('Failed to fetch'), { cause: inner }),
      'POST /bff/games/1/turns/ensure',
      '/bff/games/1/turns/ensure'
    )
    expect(e.message).toContain('cause:')
    expect(e.message).toContain('connection reset')
  })
})

describe('bffRequest (network failure)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.removeItem(INCLUDE_DIAGNOSTICS_SESSION_KEY)
  })

  it('appends includeDiagnostics=true to /bff paths when session recording is on', async () => {
    sessionStorage.setItem(INCLUDE_DIAGNOSTICS_SESSION_KEY, '1')
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ games: [] }), { status: 200 }))
    )
    vi.stubGlobal('fetch', fetchMock)
    await fetchGames()
    expect(fetchMock).toHaveBeenCalledWith(
      '/bff/games?includeDiagnostics=true',
      undefined
    )
  })

  it('fetchGames throws an error that names the BFF path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    )
    await expect(fetchGames()).rejects.toSatisfy((thrown: unknown) => {
      expect(thrown).toBeInstanceOf(Error)
      const m = (thrown as Error).message
      expect(m).toMatch(/GET \/bff\/games/)
      expect(m).toMatch(/request: \/bff\/games/)
      return true
    })
  })
})

describe('normalizeMapDataResponse', () => {
  it('copies planet onto each node as a plain object', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          planet: { id: 1, name: 'Homeworld' },
          ownerName: null,
        },
      ],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].planet).toEqual({ id: 1, name: 'Homeworld' })
    expect(out.nodes[0].planet).not.toBe((raw.nodes[0] as { planet: object }).planet)
  })

  it('parses node coordinates with parseJsonFiniteNumber (no boolean coercion)', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [
        { id: 'a', label: 'a', x: true, y: false },
        { id: 'b', label: 'b', x: '12', y: '-3' },
        { id: 'c', label: 'c', x: null, y: '' },
      ],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0]).toMatchObject({ x: 0, y: 0 })
    expect(out.nodes[1]).toMatchObject({ x: 12, y: -3 })
    expect(out.nodes[2]).toMatchObject({ x: 0, y: 0 })
  })

  it('preserves normalWellCells on base-map nodes', () => {
    const cells = [{ x: 10, y: 20 }, { x: 11, y: 20 }]
    const raw = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          planet: { id: 1 },
          normalWellCells: cells,
        },
      ],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].normalWellCells).toEqual(cells)
  })

  it('drops normalWellCells with non-integer or coercible-invalid coordinates', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          normalWellCells: [
            { x: 10, y: 20 },
            { x: null, y: 0 },
            { x: true, y: 0 },
            { x: '', y: 0 },
            { x: 10.5, y: 20 },
            { x: '11', y: '20' },
            { x: 12, y: 21 },
          ],
        },
      ],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].normalWellCells).toEqual([
      { x: 10, y: 20 },
      { x: 11, y: 20 },
      { x: 12, y: 21 },
    ])
  })

  it('reads nested snapshot from Planet key when planet is absent', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [{ id: 'p2', label: 'p2', x: 0, y: 0, Planet: { id: 2, name: 'Alt' } }],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].planet?.name).toBe('Alt')
  })

  it('keeps ion storm overlay class only when Core sends it on the wire', () => {
    const raw = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
        {
          layer: 'ion-storms',
          id: 'is-1',
          x: 10,
          y: 20,
          radius: 30,
          voltage: 120,
          class: 3,
        },
        {
          layer: 'ion-storms',
          id: 'is-2',
          x: 40,
          y: 50,
          radius: 60,
          voltage: 220,
        },
      ],
    }

    const out = normalizeMapDataResponse(raw)
    expect(out.overlayCircles).toEqual([
      {
        layer: 'ion-storms',
        id: 'is-1',
        x: 10,
        y: 20,
        radius: 30,
        voltage: 120,
        class: 3,
      },
    ])
  })

  it('keeps flare illustrativeRoute waypointOffset and arrivalOffset when valid', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            { kind: 'normal', to: { x: 0, y: 0 } },
            {
              kind: 'flare',
              to: { x: 3, y: 4 },
              waypointOffset: [10, 20],
              arrivalOffset: [5, -1],
            },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    const flare = out.routes![0].illustrativeRoute![1]
    expect(flare.waypointOffset).toEqual([10, 20])
    expect(flare.arrivalOffset).toEqual([5, -1])
  })

  it('drops illustrative steps when to.x / to.y are not finite numbers (e.g. null, empty string)', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            { kind: 'normal', to: { x: null, y: 0 } },
            { kind: 'normal', to: { x: 5, y: 6 } },
            { kind: 'normal', to: { x: '', y: 7 } },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.routes![0].illustrativeRoute).toEqual([
      { kind: 'normal', to: { x: 5, y: 6 } },
    ])
  })

  it('omits waypoint/arrival offset pairs when an element is null, empty string, or non-numeric (no coercion to 0)', () => {
    const raw: unknown = JSON.parse(
      `{
        "analyticId": "connections",
        "nodes": [],
        "edges": [],
        "routes": [
          {
            "fromPlanetId": 1,
            "toPlanetId": 2,
            "viaFlare": true,
            "illustrativeRoute": [
              {
                "kind": "flare",
                "to": { "x": 0, "y": 0 },
                "waypointOffset": [null, 1],
                "arrivalOffset": ["", 2]
              },
              { "kind": "normal", "to": { "x": 1, "y": 1 } }
            ]
          }
        ]
      }`
    )
    const out = normalizeMapDataResponse(raw)
    const step = out.routes![0].illustrativeRoute![0]
    expect(step.waypointOffset).toBeUndefined()
    expect(step.arrivalOffset).toBeUndefined()
  })

  it('accepts snake_case offset keys and omits invalid offset tuples', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            {
              kind: 'flare',
              to: { x: 0, y: 0 },
              waypoint_offset: [1, 2],
              arrival_offset: [3, 4],
            },
            {
              kind: 'flare',
              to: { x: 1, y: 1 },
              waypointOffset: [0, Number.NaN],
            },
            {
              kind: 'normal',
              to: { x: 2, y: 2 },
            },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    const steps = out.routes![0].illustrativeRoute!
    expect(steps[0].waypointOffset).toEqual([1, 2])
    expect(steps[0].arrivalOffset).toEqual([3, 4])
    expect(steps[1].waypointOffset).toBeUndefined()
    expect(steps[2].waypointOffset).toBeUndefined()
  })
})
