import { describe, expect, it } from 'vitest'
import { buildTerritoryMovieDocument } from './territoryMovieDocument'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'

const payload = {
  turn: 2,
  rectangle: { left: 0, bottom: 0, width: 100, height: 80 },
  rings: 'RINGSBLOB',
  planets: 'PLANETSBLOB',
  players: [{ id: 4, name: 'A<B' }],
  teams: [{ id: 7, name: null }],
  palette: ['#8fff00', '#fff48f', '#ab8700'],
}

describe('territory movie document', () => {
  it('contains both blobs, the controls, and the embedded runtime', () => {
    const html = buildTerritoryMovieDocument(payload)
    expect(html).toContain('RINGSBLOB')
    expect(html).toContain('PLANETSBLOB')
    expect(html).toContain('Back to turn 1')
    expect(html).toContain('>Play<')
    expect(html).toContain('>Pause<')
    expect(html).toContain('One frame forward')
    expect(html).toContain('One frame back')
    expect(html).toContain('By team')
    expect(html).toContain('Owned planets only')
    expect(html).toContain('#8fff00')
    expect(html).not.toContain('A<B')
    expect(html).toContain('A\\u003cB')
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
