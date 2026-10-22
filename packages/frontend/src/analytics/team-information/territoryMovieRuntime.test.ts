import { gzipSync } from 'node:zlib'
import { describe, expect, it, vi } from 'vitest'
import { buildTerritoryMovieDocument } from './territoryMovieDocument'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'
import { TERRITORY_MOVIE_PALETTE } from './territoryMoviePalette'

function u16(values: number[]): Uint8Array {
  const bytes = new Uint8Array(values.length * 2)
  const view = new DataView(bytes.buffer)
  values.forEach((value, index) => {
    view.setUint16(index * 2, value, true)
  })
  return bytes
}

function gzipBase64(bytes: Uint8Array): string {
  return gzipSync(bytes).toString('base64')
}

const rectangle = { left: 100, bottom: 50, width: 4000, height: 3000 }

function page(): Document {
  const html = buildTerritoryMovieDocument({
    turn: 1,
    rectangle,
    rings: 'RINGSBLOB',
    planets: 'PLANETSBLOB',
    players: [{ id: 4, name: null }],
    teams: [],
    palette: ['#112233'],
  })
  return new DOMParser().parseFromString(html, 'text/html')
}

describe('territory movie runtime', () => {
  const runtime = createTerritoryMovieRuntime()

  it('assigns the next unused index and restores it after an uncheck', () => {
    let state = runtime.initialState()
    state = runtime.toggleOwner(state, 'players', 4)
    state = runtime.toggleOwner(state, 'players', 9)
    expect(runtime.colorIndex(state, 'players', 4)).toBe(0)
    expect(runtime.colorIndex(state, 'players', 9)).toBe(1)

    state = runtime.toggleOwner(state, 'players', 4)
    expect(runtime.colorIndex(state, 'players', 4)).toBe(0)
    expect(runtime.legendRows(state, [{ id: 4, name: null }], 'players')[0]).toMatchObject({
      checked: false,
      index: 0,
    })

    state = runtime.toggleOwner(state, 'players', 1)
    expect(runtime.colorIndex(state, 'players', 1)).toBe(2)
    state = runtime.toggleOwner(state, 'players', 4)
    expect(runtime.colorIndex(state, 'players', 4)).toBe(0)

    const emptied = runtime.toggleOwner(
      runtime.toggleOwner(runtime.toggleOwner(state, 'players', 4), 'players', 9),
      'players',
      1
    )
    expect(runtime.legendRows(emptied, [{ id: 4, name: null }, { id: 1, name: 'Bo' }, { id: 9, name: 'Ada' }], 'players').every((row) => !row.checked)).toBe(true)
    expect(emptied.selections.players.nextIndex).toBe(3)
    const restored = runtime.toggleOwner(emptied, 'players', 9)
    expect(runtime.colorIndex(restored, 'players', 9)).toBe(1)
  })

  it('keeps each selection\'s indexes across frames and section switches', () => {
    let state = runtime.toggleOwner(runtime.initialState(), 'players', 4)
    state = runtime.setFrame(state, 3, 5)
    state = runtime.setByTeam(state, true)
    state = runtime.setOwnedPlanetsOnly(state, true)
    expect(runtime.colorIndex(state, 'players', 4)).toBe(0)
    state = runtime.toggleOwner(state, 'teams', 7)
    expect(runtime.colorIndex(state, 'teams', 7)).toBe(0)
    expect(runtime.colorIndex(state, 'players', 4)).toBe(0)
    expect(runtime.sectionIndex(false, false)).toBe(1)
    expect(runtime.sectionIndex(true, false)).toBe(0)
    expect(runtime.sectionIndex(true, true)).toBe(2)
    expect(runtime.sectionIndex(false, true)).toBe(3)
  })

  it('lists a selected owner on an empty frame and still paints no ring', () => {
    const state = runtime.toggleOwner(runtime.initialState(), 'players', 4)
    expect(
      runtime.legendRows(
        state,
        [
          { id: 4, name: null },
          { id: 9, name: 'Ada' },
        ],
        'players'
      )
    ).toEqual([
      { id: 4, label: '4', index: 0, checked: true },
      { id: 9, label: 'Ada', index: null, checked: false },
    ])
    expect(runtime.framePaths([], rectangle, new Set([4]))).toEqual([])
    const paths = runtime.framePaths(
      [
        { groupId: 4, vertices: [{ dx: 10, dy: 20 }, { dx: 30, dy: 40 }] },
        { groupId: 4, vertices: [{ dx: 50, dy: 60 }, { dx: 70, dy: 80 }] },
        { groupId: 9, vertices: [{ dx: 1, dy: 1 }] },
      ],
      rectangle,
      new Set([4])
    )
    expect(paths).toHaveLength(1)
    expect(paths[0]?.groupId).toBe(4)
    expect(paths[0]?.d).toBe('M101 52L103 54ZM105 56L107 58Z')
  })

  it('drops planet dots when the count disagrees or an id repeats', () => {
    expect(runtime.decodePlanets(u16([1, 3, 4, 5, 2]))).toEqual({
      valid: true,
      rows: [{ id: 3, x: 4, y: 5, firstTurn: 2 }],
    })
    expect(runtime.decodePlanets(u16([2, 3, 4, 5, 2])).valid).toBe(false)
    expect(runtime.decodePlanets(u16([2, 3, 4, 5, 1, 3, 6, 7, 2])).valid).toBe(false)
    const planets = runtime.decodePlanets(u16([1, 3, 4, 5, 2]))
    expect(runtime.visibleDots(planets, 1)).toEqual([])
    expect(runtime.visibleDots(planets, 2)).toEqual([{ id: 3, x: 4, y: 5, firstTurn: 2 }])
    expect(runtime.decodeRings(u16([1]), 1)).toBeNull()
  })

  it('flips the viewBox so host +y is up and sizes dots at 4px', () => {
    expect(runtime.viewBoxFor(rectangle)).toBe('100 -3050 4000 3000')
    expect(runtime.dotRadius(4000, 800)).toBe(10)
    expect(runtime.fittedCssWidth(rectangle, 800, 800)).toBe(800)
    expect(runtime.fittedCssWidth(rectangle, 1200, 600)).toBe(800)
    expect(runtime.PLAY_STEP_MS).toBe(2000)
  })

  it('keeps a legend row with no ring, paints dots above fills, and hides early planets', () => {
    const doc = page()
    const sections: { groupId: number; vertices: { dx: number; dy: number }[] }[][][] = [
      0, 1, 2, 3,
    ].map(() => [[], [], []])
    sections[1]![1] = [
      {
        groupId: 4,
        vertices: [
          { dx: 10, dy: 20 },
          { dx: 30, dy: 40 },
          { dx: 50, dy: 60 },
        ],
      },
    ]
    sections[0]![1] = [
      {
        groupId: 7,
        vertices: [
          { dx: 0, dy: 0 },
          { dx: 10, dy: 0 },
          { dx: 10, dy: 10 },
        ],
      },
    ]
    const bounds = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      bottom: 800,
      right: 800,
      width: 800,
      height: 800,
      toJSON() {
        return {}
      },
    })
    runtime.start(doc, {
      turn: 3,
      rectangle,
      sections,
      planets: { valid: true, rows: [{ id: 11, x: 150, y: 80, firstTurn: 2 }] },
      players: [
        { id: 4, name: null },
        { id: 9, name: 'Ada' },
      ],
      teams: [{ id: 7, name: null }],
      palette: ['#8fff00', '#00006e'],
    })
    expect(doc.getElementById('frame-title')?.textContent).toBe('1')
    expect(doc.title).toBe('1')
    const clickLegend = (index: number) => {
      const input = doc.querySelectorAll('#legend input')[index]
      if (!(input instanceof HTMLInputElement)) throw new Error('missing legend checkbox')
      input.click()
    }
    clickLegend(0)
    expect(doc.getElementById('legend')?.textContent).toContain('4')
    expect(doc.querySelector('#map path')).toBeNull()
    expect(doc.querySelector('#map circle')).toBeNull()

    doc.getElementById('frame-forward')?.dispatchEvent(new Event('click'))
    const path = doc.querySelector('#map path')
    const circle = doc.querySelector('#map circle')
    expect(path?.getAttribute('fill')).toBe('#8fff00')
    expect(path?.getAttribute('fill-opacity')).toBe('1')
    expect(path?.getAttribute('fill-rule')).toBe('evenodd')
    expect(path?.hasAttribute('stroke')).toBe(false)
    expect(circle?.getAttribute('fill')).toBe('#9ca3af')
    expect(circle?.getAttribute('r')).toBe('10')
    const painted = [...doc.querySelectorAll('#map path, #map circle')]
    expect(painted[0]?.tagName.toLowerCase()).toBe('path')
    expect(painted[1]?.tagName.toLowerCase()).toBe('circle')

    clickLegend(1)
    expect(doc.querySelector('[data-group-id="4"]')?.getAttribute('fill')).toBe('#8fff00')
    const swatches = [...doc.querySelectorAll('#legend .swatch')].map((node) =>
      node.getAttribute('data-color-index')
    )
    expect(swatches).toEqual(['0', '1'])

    clickLegend(0)
    clickLegend(0)
    expect(doc.querySelector('[data-group-id="4"]')?.getAttribute('fill')).toBe('#8fff00')

    const byTeam = doc.getElementById('by-team') as HTMLInputElement
    byTeam.checked = true
    byTeam.dispatchEvent(new Event('change', { bubbles: true }))
    expect(doc.getElementById('legend')?.textContent).toContain('7')
    expect(doc.querySelector('[data-group-id="4"]')).toBeNull()
    byTeam.checked = false
    byTeam.dispatchEvent(new Event('change', { bubbles: true }))
    expect(doc.querySelector('[data-group-id="4"]')?.getAttribute('fill')).toBe('#8fff00')
    bounds.mockRestore()
  })

  it('locks the sidebar to the measure width and keeps it when the legend changes', () => {
    const doc = page()
    const measures = doc.querySelector('.measures')
    if (!(measures instanceof HTMLElement)) throw new Error('missing measures')
    Object.defineProperty(measures, 'scrollWidth', { configurable: true, value: 240 })
    const sections: { groupId: number; vertices: { dx: number; dy: number }[] }[][][] = [
      0, 1, 2, 3,
    ].map(() => [[]])
    runtime.start(doc, {
      turn: 1,
      rectangle,
      sections,
      planets: { valid: false, rows: [] },
      players: [{ id: 4, name: 'Ada' }],
      teams: [{ id: 7, name: 'A much longer league team' }],
      palette: ['#8fff00'],
    })
    const sidebar = doc.querySelector('.sidebar')
    if (!(sidebar instanceof HTMLElement)) throw new Error('missing sidebar')
    expect(sidebar.style.width).toBe('240px')
    const byTeam = doc.getElementById('by-team') as HTMLInputElement
    byTeam.checked = true
    byTeam.dispatchEvent(new Event('change', { bubbles: true }))
    expect(sidebar.style.width).toBe('240px')
  })

  it('steps one frame every 2 seconds and returns to turn 1', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const doc = page()
    const sections: { groupId: number; vertices: { dx: number; dy: number }[] }[][][] = [
      0, 1, 2, 3,
    ].map(() => [[], [], []])
    runtime.start(doc, {
      turn: 3,
      rectangle,
      sections,
      planets: { valid: false, rows: [] },
      players: [],
      teams: [],
      palette: ['#8fff00'],
    })
    expect(doc.querySelector('circle')).toBeNull()
    doc.getElementById('play')?.dispatchEvent(new Event('click'))
    expect(doc.getElementById('frame-title')?.textContent).toBe('1')
    vi.advanceTimersByTime(2000)
    expect(doc.getElementById('frame-title')?.textContent).toBe('2')
    doc.getElementById('pause')?.dispatchEvent(new Event('click'))
    vi.advanceTimersByTime(2000)
    expect(doc.getElementById('frame-title')?.textContent).toBe('2')
    doc.getElementById('frame-forward')?.dispatchEvent(new Event('click'))
    expect(doc.getElementById('frame-title')?.textContent).toBe('3')
    doc.getElementById('frame-back')?.dispatchEvent(new Event('click'))
    expect(doc.getElementById('frame-title')?.textContent).toBe('2')
    doc.getElementById('back-to-start')?.dispatchEvent(new Event('click'))
    expect(doc.getElementById('frame-title')?.textContent).toBe('1')
    expect(doc.title).toBe('1')
    vi.useRealTimers()
  })

  it('inflates both blobs from the document payload', async () => {
    const rings = u16([0, 1, 4, 3, 10, 20, 30, 40, 50, 60, 0, 0])
    const planets = u16([1, 11, 150, 80, 1])
    const doc = new DOMParser().parseFromString(
      buildTerritoryMovieDocument({
        turn: 1,
        rectangle,
        rings: gzipBase64(rings),
        planets: gzipBase64(planets),
        players: [{ id: 4, name: 'Ada' }],
        teams: [],
        palette: ['#8fff00'],
      }),
      'text/html'
    )
    await runtime.boot(doc, {
      turn: 1,
      rectangle,
      rings: gzipBase64(rings),
      planets: gzipBase64(planets),
      players: [{ id: 4, name: 'Ada' }],
      teams: [],
      palette: ['#8fff00'],
    })
    const owner = doc.querySelector('#legend input') as HTMLInputElement
    owner.checked = true
    owner.dispatchEvent(new Event('change', { bubbles: true }))
    expect(doc.querySelector('#map path')?.getAttribute('fill')).toBe('#8fff00')
    expect(doc.querySelector('#map circle')?.getAttribute('cx')).toBe('150')
    expect(TERRITORY_MOVIE_PALETTE[0]).toBe('#8fff00')
  })
})
