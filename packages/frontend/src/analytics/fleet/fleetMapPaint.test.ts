import { describe, expect, it } from 'vitest'
import { EMPTY_FLEET_COMPONENT_CATALOG } from './fleetComponentCatalog'
import { collectFleetHeadingTrails } from './fleetHeadingTrails'
import { fleetMapPaintSlices } from './fleetMapPaint'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  type FleetLocationRingStack,
} from './fleetLocationRings'
import { formatFleetRecordField } from './fleetRecordDisplay'
import {
  fleetPlayerStreamSliceFromState,
  initialFleetPlayerStreamState,
  reduceFleetPlayerStreamState,
  type FleetPlayerStreamSlice,
} from './fleetTablePlayerStreamState'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import type { FleetTableRecord } from './fleetTableWireSchema'

const DISPLAY_TURN = 9
const STACK_X = 100
const STACK_Y = 200

function ship(
  partial: Partial<FleetTableRecord> & Pick<FleetTableRecord, 'recordId'>
): FleetTableRecord {
  return {
    disposition: 'active',
    qualifiers: {},
    fields: {
      shipId: { kind: 'known', value: 1 },
      hull: { kind: 'known', value: 24 },
      engine: { kind: 'unknown' },
      beams: { kind: 'unknown' },
      launchers: { kind: 'unknown' },
      builtTurn: { kind: 'unknown' },
      location: { kind: 'unknown' },
    },
    buildOptionSets: [],
    ...partial,
  }
}

function motion(heading: number) {
  return {
    heading,
    warp: 3,
    travelLyPerTurn: 9,
    trailStop: { x: STACK_X, y: STACK_Y + 9 },
  }
}

const ledgerSeen = ship({
  recordId: 'ledger-seen',
  militaryEstimate2x: 400,
  lastSeen: { turn: DISPLAY_TURN, x: STACK_X, y: STACK_Y },
  motion: motion(0),
})

const ledgerEarlierTurn = ship({
  recordId: 'ledger-earlier',
  militaryEstimate2x: 8000,
  lastSeen: { turn: DISPLAY_TURN - 1, x: STACK_X, y: STACK_Y },
})

const ledgerInactive = ship({
  recordId: 'ledger-inactive',
  disposition: 'lost',
  militaryEstimate2x: 8000,
  lastSeen: { turn: DISPLAY_TURN, x: STACK_X, y: STACK_Y },
})

const sightingSeen = ship({
  recordId: 'sighting-seen',
  militaryEstimate2x: 100,
  lastSeen: { turn: DISPLAY_TURN, x: STACK_X, y: STACK_Y },
  motion: motion(90),
})

const savedSeenA = ship({
  recordId: 'saved-a',
  militaryEstimate2x: 2000,
  lastSeen: { turn: DISPLAY_TURN, x: STACK_X, y: STACK_Y },
  motion: motion(180),
})

const savedSeenB = ship({
  recordId: 'saved-b',
  militaryEstimate2x: 2000,
  lastSeen: { turn: DISPLAY_TURN, x: STACK_X, y: STACK_Y },
})

function reducePlayer(events: readonly FleetTableStreamEvent[]): FleetPlayerStreamSlice {
  let state = initialFleetPlayerStreamState()
  for (const event of events) {
    state = reduceFleetPlayerStreamState(state, event)
  }
  const slice = fleetPlayerStreamSliceFromState(state)
  if (slice == null) {
    throw new Error('expected a fleet stream slice')
  }
  return slice
}

function project(playersById: ReadonlyMap<number, FleetPlayerStreamSlice>): {
  stacks: readonly FleetLocationRingStack[]
  trails: ReturnType<typeof collectFleetHeadingTrails>
} {
  const painted = fleetMapPaintSlices(playersById)
  const visible = [...playersById.keys()].map((playerId) => ({
    playerId,
    name: 'fallback',
  }))
  const ships = collectFleetLocationRingShips(
    painted,
    visible,
    EMPTY_FLEET_COMPONENT_CATALOG,
    DISPLAY_TURN
  )
  return {
    stacks: buildFleetLocationRingStacks(ships),
    trails: collectFleetHeadingTrails(painted, visible, DISPLAY_TURN, 0),
  }
}

function stackAt(
  stacks: readonly FleetLocationRingStack[],
  x: number,
  y: number
): FleetLocationRingStack {
  const stack = stacks.find((candidate) => candidate.x === x && candidate.y === y)
  if (stack == null) {
    throw new Error(`missing ring at ${x},${y}`)
  }
  return stack
}

describe('fleet map paint', () => {
  const ledgerPlayer = reducePlayer([
    {
      type: 'roster_paint',
      playerId: 3,
      paint: 'ledger',
      ledger: {
        playerId: 3,
        playerName: 'Cara',
        records: [ledgerSeen, ledgerEarlierTurn, ledgerInactive],
      },
    },
  ])
  const sightingPlayer = reducePlayer([
    {
      type: 'roster_paint',
      playerId: 5,
      paint: 'sightings',
      ledger: {
        playerId: 5,
        playerName: 'Bob',
        records: [sightingSeen],
      },
    },
  ])

  it('paints a stored ledger for one player and this turn sightings for another', () => {
    expect(ledgerPlayer.mapPaint?.source).toBe('ledger')
    expect(sightingPlayer.mapPaint?.source).toBe('sightings')
    expect(formatFleetRecordField(sightingSeen, 'beams')).toBe('?')
    expect(formatFleetRecordField(sightingSeen, 'engine')).toBe('?')
    expect(formatFleetRecordField(sightingSeen, 'launchers')).toBe('?')

    const { stacks, trails } = project(
      new Map([
        [3, ledgerPlayer],
        [5, sightingPlayer],
      ])
    )
    const stack = stackAt(stacks, STACK_X, STACK_Y)

    expect(stacks).toHaveLength(1)
    expect(stack.ships.map((entry) => entry.recordId)).toEqual(['ledger-seen', 'sighting-seen'])
    expect(stack.hostMilitaryPointsSum).toBe(250)
    expect(stack.arcs.map((arc) => ({ playerId: arc.playerId, share: arc.share }))).toEqual(
      [
        { playerId: 3, share: 0.5 },
        { playerId: 5, share: 0.5 },
      ]
    )
    expect(stack.arcs.map((arc) => arc.playerName)).toEqual(['Cara', 'Bob'])
    expect(trails.map((trail) => ({ recordId: trail.recordId, heading: trail.heading }))).toEqual([
      { recordId: 'ledger-seen', heading: 0 },
      { recordId: 'sighting-seen', heading: 90 },
    ])
    expect(trails.every((trail) => trail.x === STACK_X && trail.y === STACK_Y)).toBe(true)
  })

  it('holds that picture until a ledger save, then replaces rings, trails, and shared strength', () => {
    const chatter: readonly FleetTableStreamEvent[] = [
      {
        type: 'record_refined',
        playerId: 3,
        record: ship({
          recordId: 'ledger-seen',
          militaryEstimate2x: 2,
          lastSeen: { turn: DISPLAY_TURN, x: 1, y: 1 },
        }),
      },
      {
        type: 'ledger_updated',
        playerId: 5,
        replacesTurnLoad: false,
        ledger: {
          playerId: 5,
          playerName: 'Prior',
          records: [
            ship({
              recordId: 'inferred-prior',
              militaryEstimate2x: 9000,
              lastSeen: { turn: DISPLAY_TURN, x: 50, y: 50 },
              motion: motion(45),
            }),
          ],
        },
      },
    ]

    let heldLedger = ledgerPlayer
    let heldSightings = sightingPlayer
    for (const event of chatter) {
      if (event.playerId === 3) {
        heldLedger = reducePlayerFrom(heldLedger, event)
      }
      if (event.playerId === 5) {
        heldSightings = reducePlayerFrom(heldSightings, event)
      }
    }

    const held = project(
      new Map([
        [3, heldLedger],
        [5, heldSightings],
      ])
    )
    expect(stackAt(held.stacks, STACK_X, STACK_Y).hostMilitaryPointsSum).toBe(250)
    expect(held.stacks.map((stack) => stack.key)).toEqual([`${STACK_X},${STACK_Y}`])
    expect(heldSightings.mapPaint?.source).toBe('sightings')
    expect(heldSightings.mapPaint?.records.map((record) => record.recordId)).toEqual([
      'sighting-seen',
    ])

    const savedLedger = reducePlayerFrom(heldLedger, {
      type: 'ledger_updated',
      playerId: 3,
      ledger: {
        playerId: 3,
        playerName: 'Cara',
        records: [ledgerEarlierTurn, ledgerInactive, savedSeenA, savedSeenB],
      },
    })
    expect(savedLedger.mapPaint?.source).toBe('ledger')

    const saved = project(
      new Map([
        [3, savedLedger],
        [5, heldSightings],
      ])
    )
    const stack = stackAt(saved.stacks, STACK_X, STACK_Y)

    expect(stack.ships.map((entry) => entry.recordId)).toEqual([
      'saved-a',
      'saved-b',
      'sighting-seen',
    ])
    expect(stack.hostMilitaryPointsSum).toBe(2050)
    expect(stack.arcs.map((arc) => ({ playerId: arc.playerId, share: arc.share }))).toEqual([
      { playerId: 3, share: 2 / 3 },
      { playerId: 5, share: 1 / 3 },
    ])
    expect(stack.opacity).not.toBe(held.stacks[0]?.opacity)
    expect(saved.trails.map((trail) => ({ recordId: trail.recordId, heading: trail.heading }))).toEqual(
      [
        { recordId: 'saved-a', heading: 180 },
        { recordId: 'sighting-seen', heading: 90 },
      ]
    )
  })

  it('paints a cached ledger without a turn-load frame', () => {
    const cached = reducePlayer([
      {
        type: 'ledger_updated',
        playerId: 4,
        ledger: {
          playerId: 4,
          playerName: 'Dee',
          records: [ledgerSeen],
        },
      },
    ])

    expect(cached.mapPaint?.source).toBe('ledger')
    const { stacks } = project(new Map([[4, cached]]))
    expect(stackAt(stacks, STACK_X, STACK_Y).ships.map((entry) => entry.recordId)).toEqual([
      'ledger-seen',
    ])
  })
})

function reducePlayerFrom(
  slice: FleetPlayerStreamSlice,
  event: FleetTableStreamEvent
): FleetPlayerStreamSlice {
  const state = {
    playerName: slice.playerName ?? null,
    records: slice.records == null ? null : [...slice.records],
    rosterPaint: slice.rosterPaint ?? null,
    mapPaint: slice.mapPaint ?? null,
    discrepancyOverlay: slice.discrepancyOverlay,
    discrepancy: slice.discrepancy,
    isComplete: slice.isComplete,
    isFinal: slice.isFinal,
    isPending: slice.isPending,
    summary: slice.summary,
    error: slice.error,
  }
  const next = fleetPlayerStreamSliceFromState(reduceFleetPlayerStreamState(state, event))
  if (next == null) {
    throw new Error('expected a fleet stream slice')
  }
  return next
}
