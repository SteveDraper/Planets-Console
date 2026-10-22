import { describe, expect, it } from 'vitest'
import { buildTerritoryMovieDocument } from './territoryMovieDocument'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'

const payload = {
  turn: 2,
  rectangle: { left: 0, bottom: 0, width: 100, height: 80 },
  rings: 'RINGSBLOB',
  planets: 'PLANETSBLOB',
  players: [{ id: 4, name: 'A<B' }, { id: 9, name: 'Short' }],
  teams: [{ id: 7, name: null }, { id: 2, name: 'A much longer league team' }],
  palette: ['#8fff00', '#fff48f', '#ab8700'],
}

describe('territory movie document', () => {
  it('contains both blobs, the controls, and the embedded runtime', () => {
    const html = buildTerritoryMovieDocument(payload)
    expect(html).toContain('RINGSBLOB')
    expect(html).toContain('PLANETSBLOB')
    expect(html).toContain('aria-label="Back to turn 1"')
    expect(html).toContain('aria-label="Play"')
    expect(html).toContain('aria-label="Pause"')
    expect(html).toContain('aria-label="One frame forward"')
    expect(html).toContain('aria-label="One frame back"')
    expect(html).toContain('<svg')
    expect(html).toContain('#map { display: block; width: 100%; height: 100%; background: #000')
    expect(html).not.toContain('svg { display: block; width: 100%; height: 100%; background: #000')
    expect(html).toContain('#play, #pause { color: #b6ff4a')
    expect(html).toContain('#back-to-start, #frame-back, #frame-forward { color: #3ecbff')
    expect(html).toContain('By team')
    expect(html).toContain('Owned planets only')
    expect(html).toContain('background: #3a3f44')
    expect(html).toContain('padding: 0 0 0 1.25rem')
    const measuresAt = html.indexOf('class="measures"')
    const ownerAt = html.indexOf('class="owner-measure"')
    expect(measuresAt).toBeGreaterThan(-1)
    expect(ownerAt).toBeGreaterThan(measuresAt)
    const sidebarAt = html.indexOf('id="by-team"')
    const mapAt = html.indexOf('id="map"')
    const playAt = html.indexOf('id="play"')
    expect(sidebarAt).toBeGreaterThan(-1)
    expect(sidebarAt).toBeLessThan(mapAt)
    expect(mapAt).toBeLessThan(playAt)
    expect(html).toContain('#8fff00')
    expect(html).not.toContain('A<B')
    expect(html).toContain('A&lt;B')
    expect(html).toContain('A\\u003cB')
    expect(html).toContain('A much longer league team')
    expect(html).toContain('DecompressionStream')

    const marker = 'const runtime = ('
    const open = html.indexOf(marker)
    const close = html.indexOf(')();', open)
    const source = html.slice(open + marker.length, close)
    const runtime = new Function(`return (${source})()`)() as ReturnType<
      typeof createTerritoryMovieRuntime
    >
    expect(runtime.PLAY_STEP_MS).toBe(2000)
  })
})
