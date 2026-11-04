import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchHomeworldFleetAgeRefetch, type FleetAgeRefetchNotice } from './api'
import { homeworldLocatorMapQueryKey } from './mapAnalytic'
import {
  homeworldFleetAgeRefetchQueryKey,
  shownShellRefetchesForFleetAgeNotice,
  useHomeworldFleetAgeRefetch,
} from './useHomeworldFleetAgeRefetch'

vi.mock('./api', () => ({
  fetchHomeworldFleetAgeRefetch: vi.fn(),
}))

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 8,
  perspective: 1,
  username: 'alice',
}

const responses: Array<Promise<FleetAgeRefetchNotice>> = []

function queueNotice(notice: FleetAgeRefetchNotice) {
  responses.push(Promise.resolve(notice))
}

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children)
  }
}

describe('shownShellRefetchesForFleetAgeNotice', () => {
  it('records the first sample without refetching', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: false,
        shellTurn: 8,
        fromTurn: 2,
      })
    ).toBe(false)
  })

  it('refetches a shown shell at or after the changed turn', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 8,
        fromTurn: 8,
      })
    ).toBe(true)
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 3,
        fromTurn: 8,
      })
    ).toBe(false)
  })

  it('does not refetch when the epoch has not moved', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 8,
        fromTurn: null,
      })
    ).toBe(false)
  })
})

type RefetchPollView = {
  shouldRefetch: boolean
  sample: { epoch: number }
} | undefined

function renderRefetch(client: QueryClient, initial: AnalyticShellScope = scope) {
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const rendered = renderHook(
    ({ current }: { current: AnalyticShellScope }) => {
      useHomeworldFleetAgeRefetch(current, true)
      return client.getQueryData<RefetchPollView>(homeworldFleetAgeRefetchQueryKey(current))
    },
    { wrapper: createWrapper(client), initialProps: { current: initial } },
  )
  return { invalidate, ...rendered }
}

async function expectPoll(
  result: { current: RefetchPollView },
  expected: { epoch: number; shouldRefetch: boolean },
) {
  await waitFor(() => {
    expect(result.current).toMatchObject({
      shouldRefetch: expected.shouldRefetch,
      sample: { epoch: expected.epoch },
    })
  })
}

async function refetchPoll(client: QueryClient, current: AnalyticShellScope) {
  await client.refetchQueries({ queryKey: homeworldFleetAgeRefetchQueryKey(current) })
}

describe('useHomeworldFleetAgeRefetch', () => {
  beforeEach(() => {
    responses.length = 0
    vi.mocked(fetchHomeworldFleetAgeRefetch).mockReset()
    vi.mocked(fetchHomeworldFleetAgeRefetch).mockImplementation(() => {
      const next = responses.shift()
      if (next == null) return new Promise(() => {})
      return next
    })
  })

  it('does not invalidate the map query on the first sample', async () => {
    const client = createClient()
    queueNotice({ epoch: 4, fromTurn: 1 })
    const { result, invalidate } = renderRefetch(client)

    await expectPoll(result, { epoch: 4, shouldRefetch: false })
    expect(fetchHomeworldFleetAgeRefetch).toHaveBeenCalledWith(scope, 0)
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('invalidates the map query when a later notice is at or before the shell turn', async () => {
    const client = createClient()
    queueNotice({ epoch: 4, fromTurn: 1 })
    const { result, invalidate } = renderRefetch(client)
    await expectPoll(result, { epoch: 4, shouldRefetch: false })

    queueNotice({ epoch: 6, fromTurn: scope.turn })
    await refetchPoll(client, scope)

    await expectPoll(result, { epoch: 6, shouldRefetch: true })
    expect(fetchHomeworldFleetAgeRefetch).toHaveBeenLastCalledWith(scope, 4)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: homeworldLocatorMapQueryKey(scope),
    })
  })

  it('does not invalidate when a later notice is after the shell turn', async () => {
    const client = createClient()
    queueNotice({ epoch: 4, fromTurn: 1 })
    const { result, invalidate } = renderRefetch(client)
    await expectPoll(result, { epoch: 4, shouldRefetch: false })

    queueNotice({ epoch: 6, fromTurn: scope.turn + 1 })
    await refetchPoll(client, scope)

    await expectPoll(result, { epoch: 6, shouldRefetch: false })
    expect(fetchHomeworldFleetAgeRefetch).toHaveBeenLastCalledWith(scope, 4)
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('resets sampling when the game or perspective changes', async () => {
    const scopeB: AnalyticShellScope = { ...scope, gameId: '700001' }
    const client = createClient()
    queueNotice({ epoch: 5, fromTurn: 1 })
    const { result, invalidate, rerender } = renderRefetch(client)
    await expectPoll(result, { epoch: 5, shouldRefetch: false })

    queueNotice({ epoch: 6, fromTurn: 1 })
    await refetchPoll(client, scope)
    await expectPoll(result, { epoch: 6, shouldRefetch: true })
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: homeworldLocatorMapQueryKey(scope),
    })

    invalidate.mockClear()
    vi.mocked(fetchHomeworldFleetAgeRefetch).mockClear()
    queueNotice({ epoch: 2, fromTurn: 1 })
    rerender({ current: scopeB })

    await expectPoll(result, { epoch: 2, shouldRefetch: false })
    expect(fetchHomeworldFleetAgeRefetch).toHaveBeenCalledWith(scopeB, 0)
    expect(invalidate).not.toHaveBeenCalled()

    queueNotice({ epoch: 3, fromTurn: scopeB.turn })
    await refetchPoll(client, scopeB)
    await expectPoll(result, { epoch: 3, shouldRefetch: true })
    expect(fetchHomeworldFleetAgeRefetch).toHaveBeenLastCalledWith(scopeB, 2)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: homeworldLocatorMapQueryKey(scopeB),
    })
  })
})
