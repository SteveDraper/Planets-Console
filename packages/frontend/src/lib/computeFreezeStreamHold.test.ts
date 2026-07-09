import { describe, expect, it } from 'vitest'
import type { ComputeFreezeStatus } from '../stores/computeDiagnostics'
import {
  computeFreezeStreamHold,
  freezeStreamHoldKey,
  hasPendingPlayersForStream,
  streamSubscriptionPlayerIds,
} from './computeFreezeStreamHold'

const scope = { gameId: '628580', turn: 8, perspective: 1 }

function freezeStatus(
  overrides: Partial<ComputeFreezeStatus> = {}
): ComputeFreezeStatus {
  return {
    shell: scope,
    freezeArmed: true,
    allowlistedPlayerIds: [],
    ...overrides,
  }
}

describe('computeFreezeStreamHold', () => {
  it('does not hold when diagnostics are disabled', () => {
    expect(
      computeFreezeStreamHold(scope, {
        enabled: false,
        freezeStatus: freezeStatus(),
      })
    ).toEqual({ holding: false, expectedPlayerIds: null })
  })

  it('holds with empty expected set when enabled and freezeStatus is null (no tab / not loaded)', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: null,
    })
    expect(hold.holding).toBe(true)
    expect(hold.expectedPlayerIds).toEqual(new Set())
  })

  it('holds with empty expected set when freeze is armed and allowlist is empty', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [] }),
    })
    expect(hold.holding).toBe(true)
    expect(hold.expectedPlayerIds).toEqual(new Set())
  })

  it('holds with allowlisted players only', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [3, 7] }),
    })
    expect(hold.holding).toBe(true)
    expect(hold.expectedPlayerIds).toEqual(new Set([3, 7]))
  })

  it('does not hold when freezeStatus is loaded and freeze is disarmed', () => {
    expect(
      computeFreezeStreamHold(scope, {
        enabled: true,
        freezeStatus: freezeStatus({ freezeArmed: false }),
      })
    ).toEqual({ holding: false, expectedPlayerIds: null })
  })

  it('same-game turn change while freezeArmed holds with empty expected set', () => {
    const hold = computeFreezeStreamHold(
      { gameId: '628580', turn: 9, perspective: 1 },
      {
        enabled: true,
        freezeStatus: freezeStatus({
          shell: { gameId: '628580', turn: 8, perspective: 1 },
          freezeArmed: true,
          allowlistedPlayerIds: [3, 7],
        }),
      }
    )
    expect(hold.holding).toBe(true)
    expect(hold.expectedPlayerIds).toEqual(new Set())
  })

  it('same-game perspective change while freezeArmed holds with empty expected set', () => {
    const hold = computeFreezeStreamHold(
      { gameId: '628580', turn: 8, perspective: 2 },
      {
        enabled: true,
        freezeStatus: freezeStatus({
          shell: { gameId: '628580', turn: 8, perspective: 1 },
          freezeArmed: true,
          allowlistedPlayerIds: [3],
        }),
      }
    )
    expect(hold.holding).toBe(true)
    expect(hold.expectedPlayerIds).toEqual(new Set())
  })

  it('game change while freezeArmed is not holding', () => {
    const hold = computeFreezeStreamHold(
      { gameId: '999', turn: 8, perspective: 1 },
      {
        enabled: true,
        freezeStatus: freezeStatus({
          shell: { gameId: '628580', turn: 8, perspective: 1 },
          freezeArmed: true,
          allowlistedPlayerIds: [3],
        }),
      }
    )
    expect(hold).toEqual({ holding: false, expectedPlayerIds: null })
  })
})

describe('streamSubscriptionPlayerIds', () => {
  it('freeze + empty allowlist subscribes to none', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [] }),
    })
    expect(streamSubscriptionPlayerIds([3, 7, 11], hold)).toEqual([])
    expect(freezeStreamHoldKey(hold)).toBe('freeze:')
  })

  it('freeze + allowlist intersects requested players', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [7, 99] }),
    })
    expect(streamSubscriptionPlayerIds([3, 7, 11], hold)).toEqual([7])
  })
})

describe('hasPendingPlayersForStream', () => {
  it('freeze + empty allowlist is not pending (stay held, do not exhaust as failure)', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [] }),
    })
    expect(hasPendingPlayersForStream([3, 7, 11], () => false, hold)).toBe(false)
  })

  it('freeze + allowlist only waits on allowlisted players', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ allowlistedPlayerIds: [3] }),
    })
    const complete = new Set<number>()
    expect(
      hasPendingPlayersForStream([3, 7], (id) => complete.has(id), hold)
    ).toBe(true)
    complete.add(3)
    expect(
      hasPendingPlayersForStream([3, 7], (id) => complete.has(id), hold)
    ).toBe(false)
  })

  it('without freeze waits on all requested players', () => {
    const hold = computeFreezeStreamHold(scope, {
      enabled: true,
      freezeStatus: freezeStatus({ freezeArmed: false }),
    })
    expect(hasPendingPlayersForStream([3, 7], () => false, hold)).toBe(true)
  })
})
