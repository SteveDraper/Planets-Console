import { describe, it, expect } from 'vitest'
import type { GameInfoShellContext } from '../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import {
  deriveAnalyticScope,
  deriveSelectedViewpointName,
  deriveShellTurnMax,
  deriveShellViewpoints,
  deriveTurnBlockedNoLogin,
  deriveTurnDataReady,
  deriveTurnEnsureEnabled,
  deriveTurnView,
  isFutureTurn,
  isViewpointChangeAllowed,
  shouldClearInProgressPerspectiveOverride,
  type ShellContextInputs,
} from './shellContext'

const perspectives = [
  { ordinal: 1, name: 'Alice', raceName: 'Feds' as string | null },
  { ordinal: 2, name: 'Bob', raceName: 'Lizards' as string | null },
  { ordinal: 3, name: 'Carol', raceName: null as string | null },
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
    perspectiveOverrideName: null,
    loginName: 'Alice',
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
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

describe('isFutureTurn', () => {
  it('returns true when selected turn exceeds shell turn max', () => {
    expect(isFutureTurn(12, 10)).toBe(true)
    expect(isFutureTurn(10, 10)).toBe(false)
  })

  it('delegates to deriveTurnView', () => {
    const view = deriveTurnView(12, 10)
    expect(isFutureTurn(12, 10)).toBe(view.isFuture)
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
      { name: 'Alice', raceName: 'Feds', disabled: false },
      { name: 'Bob', raceName: 'Lizards', disabled: false },
      { name: 'Carol', raceName: null, disabled: false },
    ])
  })

  it('disables non-login viewpoints when game is in progress', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    const rows = deriveShellViewpoints(
      baseInputs({ gameInfoContext: ctx, loginName: 'Bob' })
    )
    expect(rows.find((r) => r.name === 'Bob')?.disabled).toBe(false)
    expect(rows.find((r) => r.name === 'Alice')?.disabled).toBe(true)
    expect(rows.find((r) => r.name === 'Carol')?.disabled).toBe(true)
  })

  it('adds spectator viewpoint when in-progress and login is not a player', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    const rows = deriveShellViewpoints(
      baseInputs({ gameInfoContext: ctx, loginName: 'Unknown' })
    )
    expect(rows[0]).toEqual({ name: '<Spectator>', raceName: null, disabled: false })
    expect(rows.find((r) => r.name === 'Alice')?.disabled).toBe(true)
    expect(rows.find((r) => r.name === 'Bob')?.disabled).toBe(true)
  })

  it('filters by stored perspectives in storage-only mode without login', () => {
    const rows = deriveShellViewpoints(
      baseInputs({
        loginName: '',
        storageOnlyLoad: true,
        storageAvailablePerspectives: [2],
      })
    )
    expect(rows.find((r) => r.name === 'Bob')?.disabled).toBe(false)
    expect(rows.find((r) => r.name === 'Alice')?.disabled).toBe(true)
  })

  it('includes spectator row when pseudo perspective 0 is stored', () => {
    const rows = deriveShellViewpoints(
      baseInputs({
        loginName: '',
        storageOnlyLoad: true,
        storageAvailablePerspectives: [0],
      })
    )
    expect(rows[0]).toEqual({ name: '<Spectator>', raceName: null, disabled: false })
    expect(rows.every((r) => r.name === '<Spectator>' || r.disabled)).toBe(true)
  })
})

describe('deriveSelectedViewpointName', () => {
  it('returns null when no perspectives', () => {
    expect(
      deriveSelectedViewpointName(
        baseInputs({ gameInfoContext: { ...baseInputs().gameInfoContext!, perspectives: [] } })
      )
    ).toBeNull()
  })

  it('uses login-matched player for in-progress games', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    expect(
      deriveSelectedViewpointName(
        baseInputs({ gameInfoContext: ctx, loginName: 'Bob', perspectiveOverrideName: 'Alice' })
      )
    ).toBe('Bob')
  })

  it('selects spectator when in-progress and login is not a player', () => {
    const ctx = shellContext({ isGameFinished: false, sectorDisplayName: null })
    expect(
      deriveSelectedViewpointName(
        baseInputs({ gameInfoContext: ctx, loginName: 'Unknown', perspectiveOverrideName: 'Alice' })
      )
    ).toBe('<Spectator>')
  })

  it('uses override when game is finished', () => {
    expect(
      deriveSelectedViewpointName(baseInputs({ perspectiveOverrideName: 'Carol' }))
    ).toBe('Carol')
  })

  it('prefers override in storage-only mode without login', () => {
    expect(
      deriveSelectedViewpointName(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [2],
          perspectiveOverrideName: 'Bob',
        })
      )
    ).toBe('Bob')
  })

  it('falls back to first stored perspective in storage-only mode', () => {
    expect(
      deriveSelectedViewpointName(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [3],
          perspectiveOverrideName: null,
        })
      )
    ).toBe('Carol')
  })

  it('selects spectator when only pseudo perspective 0 is stored', () => {
    expect(
      deriveSelectedViewpointName(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [0],
          perspectiveOverrideName: null,
        })
      )
    ).toBe('<Spectator>')
  })

  it('honours spectator override in storage-only mode when slot 0 is stored', () => {
    expect(
      deriveSelectedViewpointName(
        baseInputs({
          loginName: '',
          storageOnlyLoad: true,
          storageAvailablePerspectives: [0, 2],
          perspectiveOverrideName: '<Spectator>',
        })
      )
    ).toBe('<Spectator>')
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
    expect(deriveAnalyticScope(baseInputs({ perspectiveOverrideName: 'Bob' }))).toEqual({
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
        baseInputs({ gameInfoContext: ctx, loginName: 'Unknown', perspectiveOverrideName: 'Alice' })
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
          perspectiveOverrideName: null,
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
      shouldClearInProgressPerspectiveOverride(inProgress, 'Bob', 'Alice')
    ).toBe(true)
  })

  it('keeps matching override', () => {
    expect(
      shouldClearInProgressPerspectiveOverride(inProgress, 'Bob', 'Bob')
    ).toBe(false)
  })

  it('does nothing for finished games', () => {
    expect(
      shouldClearInProgressPerspectiveOverride(baseInputs().gameInfoContext, 'Bob', 'Alice')
    ).toBe(false)
  })
})

describe('isViewpointChangeAllowed', () => {
  const inProgress = shellContext({ isGameFinished: false, sectorDisplayName: null })

  it('allows spectator only when login is not a player during in-progress game', () => {
    expect(
      isViewpointChangeAllowed('<Spectator>', inProgress, 'Unknown', false, null, perspectives)
    ).toBe(true)
    expect(
      isViewpointChangeAllowed('Alice', inProgress, 'Unknown', false, null, perspectives)
    ).toBe(false)
  })

  it('allows login player only during in-progress game', () => {
    expect(
      isViewpointChangeAllowed('Bob', inProgress, 'Bob', false, null, perspectives)
    ).toBe(true)
    expect(
      isViewpointChangeAllowed('Alice', inProgress, 'Bob', false, null, perspectives)
    ).toBe(false)
  })

  it('allows stored perspectives in storage-only mode', () => {
    expect(
      isViewpointChangeAllowed('Bob', baseInputs().gameInfoContext, '', true, [2], perspectives)
    ).toBe(true)
    expect(
      isViewpointChangeAllowed('Alice', baseInputs().gameInfoContext, '', true, [2], perspectives)
    ).toBe(false)
  })

  it('allows spectator in storage-only mode when slot 0 is stored', () => {
    expect(
      isViewpointChangeAllowed('<Spectator>', baseInputs().gameInfoContext, '', true, [0], perspectives)
    ).toBe(true)
    expect(
      isViewpointChangeAllowed('Alice', baseInputs().gameInfoContext, '', true, [0], perspectives)
    ).toBe(false)
  })

  it('allows any player when game is finished', () => {
    expect(
      isViewpointChangeAllowed('Carol', baseInputs().gameInfoContext, 'Alice', false, null, perspectives)
    ).toBe(true)
  })
})
