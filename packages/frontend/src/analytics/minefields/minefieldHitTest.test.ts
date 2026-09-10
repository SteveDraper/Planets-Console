import { describe, expect, it } from 'vitest'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import {
  formatMinefieldHoverLines,
  knownMinefieldsAtPoint,
} from './minefieldHitTest'
import type { KnownMinefield } from './wireSchema'

function field(partial: Partial<KnownMinefield> & Pick<KnownMinefield, 'id'>): KnownMinefield {
  return {
    ownerId: 1,
    isWeb: false,
    isHidden: false,
    x: 100,
    y: 100,
    units: 100,
    infoTurn: 50,
    friendlyCode: '',
    preRadius: 10,
    postRadius: 9,
    ...partial,
  }
}

const roster: PerspectiveRow[] = [
  {
    ordinal: 1,
    playerId: 1,
    name: 'Alice',
    raceName: null,
    eliminationTurn: null,
  },
  {
    ordinal: 2,
    playerId: 2,
    name: 'Bob',
    raceName: null,
    eliminationTurn: null,
  },
]

describe('knownMinefieldsAtPoint', () => {
  it('returns every enabled-type field whose pre-decay disk contains the pointer, smallest first', () => {
    const fields = [
      field({ id: 3, x: 100, y: 100, preRadius: 20, isWeb: true }),
      field({ id: 1, x: 100, y: 100, preRadius: 10 }),
      field({ id: 2, x: 100, y: 100, preRadius: 10, isWeb: true }),
      field({ id: 9, x: 200, y: 100, preRadius: 5 }),
    ]
    const hits = knownMinefieldsAtPoint(fields, 100, 100, new Set(['normal', 'web']))
    expect(hits.map((f) => f.id)).toEqual([1, 2, 3])
  })

  it('omits disabled types', () => {
    const fields = [
      field({ id: 1, preRadius: 10, isWeb: false }),
      field({ id: 2, preRadius: 10, isWeb: true }),
    ]
    expect(knownMinefieldsAtPoint(fields, 100, 100, new Set(['web'])).map((f) => f.id)).toEqual([
      2,
    ])
  })
})

describe('formatMinefieldHoverLines', () => {
  it('lists type, owner, units, radii, infoturn, and friendly code', () => {
    const lines = formatMinefieldHoverLines(
      [
        field({
          id: 1,
          ownerId: 1,
          units: 85,
          preRadius: 9,
          postRadius: 8,
          infoTurn: 40,
          friendlyCode: 'abc',
          isWeb: true,
        }),
      ],
      roster,
      50
    )
    expect(lines).toEqual(['web · Alice · 85 units · pre 9 / post 8 · turn 40 (stale) · abc'])
  })

  it('omits empty friendly codes and does not mark current infoturn stale', () => {
    const lines = formatMinefieldHoverLines(
      [field({ id: 1, ownerId: 2, infoTurn: 50, friendlyCode: '' })],
      roster,
      50
    )
    expect(lines).toEqual(['normal · Bob · 100 units · pre 10 / post 9 · turn 50'])
  })
})
