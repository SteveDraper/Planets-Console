import { describe, it, expect } from 'vitest'
import type { GameInfoShellContext } from '../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import {
  deriveAnalyticScope,
  deriveSelectedViewpointOrdinal,
  deriveShellTurnMax,
  deriveShellViewpoints,
  deriveTurnBlockedNoLogin,
  deriveTurnDataReady,
  deriveTurnEnsureEnabled,
  deriveTurnView,
  isViewpointChangeAllowed,
  shouldClearInProgressPerspectiveOverride,
  type ShellContextInputs,
} from './shellContext'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'

const perspectives = [
  perspectiveRow(1, 'Alice', { raceName: 'Feds' }),
  perspectiveRow(2, 'Bob', { raceName: 'Lizards' }),
  perspectiveRow(3, 'Carol'),
]

function shellContext(overrides: Partial<GameInfoShellContext> = {}): GameInfoShellContext {
  return {
    turn: 10,
    perspectives,
    isGameFinished: true,
    sectorDisplayName: 'Test Sector',
    stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    ...overrides,
  }
}

function baseInputs(overrides: Partial<ShellContextInputs> = {}): ShellContextInputs {
  return {
    selectedGameId: '628580',
    gameInfoContext: shellContext(),
    selectedTurn: 5,
    perspectiveOverrideOrdinal: null,
    loginName: 'Alice',
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
    viewedDataTurn: 5,
    turnUsernamesByPlayerId: null,
    ...overrides,
  }
}

describe('deriveShellTurnMax', () => {
  it('uses latest turn from game info context', () => {
    const ctx = shellContext({ turn: 50, isGameFinished: false, sectorDisplayName: null })
    expect(deriveShellTurnMax(ctx)).toBe(50)
  })
})

describe('deriveTurnView', () => {
  it('returns null data turn when selected turn is null', () => {
    expect(deriveTurnView(null, 10)).toEqual({
      selectedTurn: null,
      dataTurn: null,
      futureOffset: 0,
      isFuture: false,
    })
  })

  it('uses selected turn as data turn when shell turn max is null', () => {
    expect(deriveTurnView(5, null)).toEqual({
      selectedTurn: 5,
      dataTurn: 5,
      futureOffset: 0,
      isFuture: false,
    })
  })

  it('passes through when selected turn is at or before shell turn max', () => {
    expect(deriveTurnView(8, 10)).toEqual({
      selectedTurn: 8,
      dataTurn: 8,
      futureOffset: 0,
      isFuture: false,
    })
    expect(deriveTurnView(10, 10)).toEqual({
      selectedTurn: 10,
      dataTurn: 10,
      futureOffset: 0,
      isFuture: false,
    })
  })

  it('caps data turn and sets future offset when viewing the future', () => {
    expect(deriveTurnView(12, 10)).toEqual({
      selectedTurn: 12,
      dataTurn: 10,
      futureOffset: 2,
      isFuture: true,
    })
  })
})

describe('deriveShellViewpoints', () => {
  it('returns empty when no perspectives', () => {
    expect(
      deriveShellViewpoints(
        baseInputs({ gameInfoContext: { ...baseInputs().gameInfoContext!, perspectives: [] } })
      )
    ).toEqual([])
  })

  it('enables all viewpoints when game is finished', () => {
    const rows = deriveShellViewpoints(baseInputs())
    expect(rows).toEqual([
      { ordinal: 1, displayName: 'Alice', raceName: 'Feds', disabled: false },
      { ordinal: 2, displayName: 'Bob', raceName: 'Lizards', disabled: false },
      { ordinal: 3, displayName: 'Carol', raceName: null, disabled: false },
    ])
  })

  it('disables non-login viewpoints when game is in progress', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    const rows = deriveShellViewpoints(
      baseInputs({ gameInfoContext: ctx, loginName: 'Bob' })
    )
    expect(rows.find((r) => r.ordinal === 2)?.disabled).toBe(false)
    expect(rows.find((r) => r.ordinal === 1)?.disabled).toBe(true)
    expect(rows.find((r) => r.ordinal === 3)?.disabled).toBe(true)
  })

  it('adds spectator viewpoint when in-progress and login is not a player', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    const rows = deriveShellViewpoints(
      baseInputs({ gameInfoContext: ctx, loginName: 'Unknown' })
    )
    expect(rows[0]).toEqual({
      ordinal: 0,
      displayName: '<Spectator>',
      raceName: null,
      disabled: false,
    })
    expect(rows.find((r) => r.ordinal === 1)?.disabled).toBe(true)
    expect(rows.find((r) => r.ordinal === 2)?.disabled).toBe(true)
  })

  it('filters by stored perspectives in storage-only mode without login', () => {
    const rows = deriveShellViewpoints(
      baseInputs({
        loginName: '',
        storageOnlyLoad: true,
        storageAvailablePerspectives: [2],
      })
    )
    expect(rows.find((r) => r.ordinal === 2)?.disabled).toBe(false)
    expect(rows.find((r) => r.ordinal === 1)?.disabled).toBe(true)
  })

  it('includes spectator row when pseudo perspective 0 is stored', () => {
    const rows = deriveShellViewpoints(
      baseInputs({
        loginName: '',
        storageOnlyLoad: true,
        storageAvailablePerspectives: [0],
      })
    )
    expect(rows[0]).toEqual({
      ordinal: 0,
      displayName: '<Spectator>',
      raceName: null,
      disabled: false,
    })
    expect(rows.every((r) => r.ordinal === 0 || r.disabled)).toBe(true)
  })

  it('uses turn-scoped usernames before elimination when viewing an earlier turn', () => {
    const rows = deriveShellViewpoints(
      baseInputs({
        gameInfoContext: shellContext({
          perspectives: [
            perspectiveRow(1, 'dead', {
              playerId: 1,
              raceName: 'Feds',
              eliminationTurn: 49,
            }),
          ],
        }),
        viewedDataTurn: 8,
        turnUsernamesByPlayerId: new Map([[1, 'dougp314']]),
      })
    )
    expect(rows[0]?.displayName).toBe('dougp314')
  })
})

describe('deriveSelectedViewpointOrdinal', () => {
  it('returns null when no perspectives', () => {
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({ gameInfoContext: { ...baseInputs().gameInfoContext!, perspectives: [] } })
      )
    ).toBeNull()
  })

  it('uses login-matched player for in-progress games', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({ gameInfoContext: ctx, loginName: 'Bob', perspectiveOverrideOrdinal: 1 })
      )
    ).toBe(2)
  })

  it('selects spectator when in-progress and login is not a player', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({ gameInfoContext: ctx, loginName: 'Unknown', perspectiveOverrideOrdinal: 1 })
      )
    ).toBe(0)
  })

  it('uses override when game is finished', () => {
    expect(
      deriveSelectedViewpointOrdinal(baseInputs({ perspectiveOverrideOrdinal: 3 }))
    ).toBe(3)
  })

  it('prefers override in storage-only mode without login', () => {
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [2],
          perspectiveOverrideOrdinal: 2,
        })
      )
    ).toBe(2)
  })

  it('falls back to first stored perspective in storage-only mode', () => {
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [3],
          perspectiveOverrideOrdinal: null,
        })
      )
    ).toBe(3)
  })

  it('selects spectator when only pseudo perspective 0 is stored', () => {
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [0],
          perspectiveOverrideOrdinal: null,
        })
      )
    ).toBe(0)
  })

  it('honours spectator override in storage-only mode when slot 0 is stored', () => {
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [0, 2],
          perspectiveOverrideOrdinal: 0,
        })
      )
    ).toBe(0)
  })

  it('resolves duplicate dead usernames to the overridden ordinal', () => {
    const deadPerspectives = [
      perspectiveRow(1, 'dead', { playerId: 1, raceName: 'Feds', eliminationTurn: 49 }),
      perspectiveRow(2, 'dead', { playerId: 2, raceName: 'Rebels', eliminationTurn: 60 }),
    ]
    expect(
      deriveSelectedViewpointOrdinal(
        baseInputs({
          gameInfoContext: shellContext({ perspectives: deadPerspectives }),
          perspectiveOverrideOrdinal: 2,
        })
      )
    ).toBe(2)
  })
})

describe('deriveAnalyticScope', () => {
  it('returns null when game id missing', () => {
    expect(deriveAnalyticScope(baseInputs({ selectedGameId: null }))).toBeNull()
  })

  it('returns null when turn missing', () => {
    expect(deriveAnalyticScope(baseInputs({ selectedTurn: null }))).toBeNull()
  })

  it('returns null when viewpoint cannot resolve to perspective', () => {
    expect(
      deriveAnalyticScope(
        baseInputs({
          gameInfoContext: shellContext({
            perspectives: [],
          }),
        })
      )
    ).toBeNull()
  })

  it('returns scope with resolved perspective ordinal', () => {
    expect(deriveAnalyticScope(baseInputs({ perspectiveOverrideOrdinal: 2 }))).toEqual({
      gameId: '628580',
      turn: 5,
      perspective: 2,
    })
  })

  it('loads latest stored turn data when selected turn is in the future', () => {
    expect(deriveAnalyticScope(baseInputs({ selectedTurn: 12 }))).toEqual({
      gameId: '628580',
      turn: 10,
      perspective: 1,
    })
  })

  it('uses pseudo-viewpoint 0 when in-progress and login is not a player', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    expect(
      deriveAnalyticScope(
        baseInputs({ gameInfoContext: ctx, loginName: 'Unknown', perspectiveOverrideOrdinal: 1 })
      )
    ).toEqual({
      gameId: '628580',
      turn: 5,
      perspective: 0,
    })
  })

  it('resolves spectator scope in storage-only mode when slot 0 is stored', () => {
    expect(
      deriveAnalyticScope(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [0],
          perspectiveOverrideOrdinal: null,
        })
      )
    ).toEqual({
      gameId: '628580',
      turn: 5,
      perspective: 0,
    })
  })
})

describe('turn ensure gating', () => {
  const scope = { gameId: '628580', turn: 5, perspective: 1 }

  it('enables ensure when scope complete and login set', () => {
    expect(deriveTurnEnsureEnabled(scope, 'Alice', false)).toBe(true)
  })

  it('enables ensure in storage-only mode without login', () => {
    expect(deriveTurnEnsureEnabled(scope, '', true)).toBe(true)
  })

  it('disables ensure when scope incomplete', () => {
    expect(deriveTurnEnsureEnabled(null, 'Alice', false)).toBe(false)
  })

  it('blocks analytics when scope set but login missing and not storage-only', () => {
    expect(deriveTurnBlockedNoLogin(scope, '', false)).toBe(true)
  })

  it('does not block when storage-only', () => {
    expect(deriveTurnBlockedNoLogin(scope, '', true)).toBe(false)
  })

  it('turnDataReady requires enabled and success', () => {
    expect(deriveTurnDataReady(true, true)).toBe(true)
    expect(deriveTurnDataReady(false, true)).toBe(false)
    expect(deriveTurnDataReady(true, false)).toBe(false)
  })
})

describe('shouldClearInProgressPerspectiveOverride', () => {
  const inProgress = shellContext({ isGameFinished: false, sectorDisplayName: null })

  it('clears override that does not match login for in-progress game', () => {
    expect(
      shouldClearInProgressPerspectiveOverride(inProgress, 'Bob', 1)
    ).toBe(true)
  })

  it('keeps matching override', () => {
    expect(
      shouldClearInProgressPerspectiveOverride(inProgress, 'Bob', 2)
    ).toBe(false)
  })

  it('does nothing for finished games', () => {
    expect(
      shouldClearInProgressPerspectiveOverride(baseInputs().gameInfoContext, 'Bob', 1)
    ).toBe(false)
  })
})

describe('isViewpointChangeAllowed', () => {
  const inProgress = shellContext({ isGameFinished: false, sectorDisplayName: null })

  it('allows spectator only when login is not a player during in-progress game', () => {
    expect(isViewpointChangeAllowed(0, inProgress, 'Unknown', false, null)).toBe(true)
    expect(isViewpointChangeAllowed(1, inProgress, 'Unknown', false, null)).toBe(false)
  })

  it('allows login player only during in-progress game', () => {
    expect(isViewpointChangeAllowed(2, inProgress, 'Bob', false, null)).toBe(true)
    expect(isViewpointChangeAllowed(1, inProgress, 'Bob', false, null)).toBe(false)
  })

  it('allows stored perspectives in storage-only mode', () => {
    expect(isViewpointChangeAllowed(2, baseInputs().gameInfoContext, '', true, [2])).toBe(true)
    expect(isViewpointChangeAllowed(1, baseInputs().gameInfoContext, '', true, [2])).toBe(false)
  })

  it('allows spectator in storage-only mode when slot 0 is stored', () => {
    expect(isViewpointChangeAllowed(0, baseInputs().gameInfoContext, '', true, [0])).toBe(true)
    expect(isViewpointChangeAllowed(1, baseInputs().gameInfoContext, '', true, [0])).toBe(false)
  })

  it('allows any player when game is finished', () => {
    expect(isViewpointChangeAllowed(3, baseInputs().gameInfoContext, 'Alice', false, null)).toBe(
      true
    )
  })
})
