import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { postBackfillWalksStop } from '../api/backfillWalksClient'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { SHELL_STORAGE_KEY, useShellStore, type GameInfoShellContext } from '../stores/shell'
import {
  installBackfillWalkStopOnShellGameChange,
  pendingBackfillWalkStop,
  requestBackfillWalkStop,
} from './backfillWalkStop'
import { deferredStopResponse, flushMicrotasks } from './backfillWalkStopTestFixtures'

vi.mock('../api/backfillWalksClient', () => ({
  postBackfillWalksStop: vi.fn(),
}))

const postStop = vi.mocked(postBackfillWalksStop)

const GAME_INFO: GameInfoShellContext = {
  turn: 10,
  perspectives: [],
  isGameFinished: true,
  sectorDisplayName: null,
  stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
  homeworldInactiveReason: null,
}

beforeEach(() => {
  postStop.mockReset()
  postStop.mockResolvedValue(undefined)
})

describe('requestBackfillWalkStop', () => {
  it('chains a second stop for the same game after the first settles', async () => {
    const first = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise)

    const firstStop = requestBackfillWalkStop('100')
    const secondStop = requestBackfillWalkStop('100')
    await Promise.resolve()

    expect(postStop).toHaveBeenCalledTimes(1)
    expect(pendingBackfillWalkStop('100')).toBe(secondStop)

    first.resolve()
    await firstStop
    await secondStop

    expect(postStop).toHaveBeenCalledTimes(2)
    expect(postStop).toHaveBeenNthCalledWith(2, '100')
  })

  it('does not chain stops for different games', async () => {
    const first = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise)

    const stopA = requestBackfillWalkStop('100')
    const stopB = requestBackfillWalkStop('200')
    await stopB

    expect(postStop).toHaveBeenCalledTimes(2)
    expect(pendingBackfillWalkStop('100')).toBe(stopA)
    first.resolve()
    await stopA
  })

  it('deletes the entry once its chain settles', async () => {
    const stop = requestBackfillWalkStop('100')
    expect(pendingBackfillWalkStop('100')).toBe(stop)

    await stop

    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })

  it('keeps a later chain when an earlier one settles', async () => {
    const first = deferredStopResponse()
    const second = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const firstStop = requestBackfillWalkStop('100')
    const secondStop = requestBackfillWalkStop('100')
    first.resolve()
    await firstStop

    expect(pendingBackfillWalkStop('100')).toBe(secondStop)
    second.resolve()
    await secondStop
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })

  it('resolves and logs when the stop fails, and a chained stop still runs', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    postStop.mockRejectedValueOnce(new Error('503 (POST /bff/games/100/backfill-walks/stop)'))

    const failedStop = requestBackfillWalkStop('100')
    const chainedStop = requestBackfillWalkStop('100')

    await expect(failedStop).resolves.toBeUndefined()
    await expect(chainedStop).resolves.toBeUndefined()
    expect(postStop).toHaveBeenCalledTimes(2)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
    warn.mockRestore()
  })
})

describe('installBackfillWalkStopOnShellGameChange', () => {
  let uninstall: () => void

  beforeEach(() => {
    window.localStorage.removeItem(SHELL_STORAGE_KEY)
    useShellStore.setState({ selectedGameId: null, lastShellGameId: null })
    uninstall = installBackfillWalkStopOnShellGameChange()
  })

  afterEach(async () => {
    uninstall()
    await Promise.all(['100', '200'].map((gameId) => pendingBackfillWalkStop(gameId)))
  })

  it('does not stop on the first game load', async () => {
    useShellStore.getState().applyGameInfoRefresh('100', GAME_INFO)
    await flushMicrotasks()

    expect(postStop).not.toHaveBeenCalled()
  })

  it('does not stop on a same-game refresh', async () => {
    useShellStore.getState().applyGameInfoRefresh('100', GAME_INFO)
    useShellStore.getState().applyGameInfoRefresh('100', { ...GAME_INFO, turn: 11 })
    useShellStore.getState().setSelectedTurn(4)
    await flushMicrotasks()

    expect(postStop).not.toHaveBeenCalled()
  })

  it('does not stop on persist hydration', async () => {
    window.localStorage.setItem(
      SHELL_STORAGE_KEY,
      JSON.stringify({ state: { selectedGameId: '100', lastShellGameId: '100' }, version: 2 })
    )

    await useShellStore.persist.rehydrate()
    await flushMicrotasks()

    expect(useShellStore.getState().selectedGameId).toBe('100')
    expect(postStop).not.toHaveBeenCalled()
  })

  it('stops the game left when the shell changes to another game', async () => {
    useShellStore.getState().applyGameInfoRefresh('100', GAME_INFO)
    useShellStore.getState().applyGameInfoRefresh('200', GAME_INFO)

    await pendingBackfillWalkStop('100')
    expect(postStop).toHaveBeenCalledTimes(1)
    expect(postStop).toHaveBeenCalledWith('100')
  })

  it('stops the game left when the shell clears its game', async () => {
    useShellStore.getState().applyGameInfoRefresh('100', GAME_INFO)
    useShellStore.setState({ selectedGameId: null })

    await pendingBackfillWalkStop('100')
    expect(postStop).toHaveBeenCalledTimes(1)
    expect(postStop).toHaveBeenCalledWith('100')
  })

  it('chains the stops of a rapid G to H to G to H', async () => {
    const first = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise)
    const { applyGameInfoRefresh } = useShellStore.getState()

    applyGameInfoRefresh('100', GAME_INFO)
    applyGameInfoRefresh('200', GAME_INFO)
    applyGameInfoRefresh('100', GAME_INFO)
    applyGameInfoRefresh('200', GAME_INFO)
    const pendingStop = pendingBackfillWalkStop('100')
    await Promise.resolve()

    expect(postStop.mock.calls.map(([gameId]) => gameId)).toEqual(['100', '200'])
    first.resolve()
    await pendingStop
    expect(postStop.mock.calls.map(([gameId]) => gameId)).toEqual(['100', '200', '100'])
  })
})
