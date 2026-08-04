import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { postHomeworldLocatorAssertion } from './api'
import {
  homeworldLocatorAssertionMutationKey,
  useHomeworldLocatorAssertionError,
  useHomeworldLocatorAssertionMutation,
  useHomeworldLocatorAssertionPending,
} from './useHomeworldLocatorMutations'
import type { HomeworldLocatorPayload } from './wireSchema'

const emptyPayload: HomeworldLocatorPayload = {
  analyticId: 'homeworld-locator',
  available: true,
  baselineDegraded: false,
  markers: [],
  rows: [],
}

vi.mock('./api', () => ({
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
  username: 'alice',
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('homeworldLocatorAssertionMutationKey', () => {
  it('scopes the mutation key by analytic scope', () => {
    const otherTurn: AnalyticShellScope = { ...scope, turn: 6 }
    expect(homeworldLocatorAssertionMutationKey(scope)).not.toEqual(
      homeworldLocatorAssertionMutationKey(otherTurn)
    )
  })
})

describe('useHomeworldLocatorAssertionMutation', () => {
  beforeEach(() => {
    vi.mocked(postHomeworldLocatorAssertion).mockReset()
  })

  it('shares pending state across hook instances via mutationKey', async () => {
    vi.mocked(postHomeworldLocatorAssertion).mockImplementation(() => new Promise(() => {}))
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const wrapper = createWrapper(client)

    const hookA = renderHook(
      () => ({
        mutation: useHomeworldLocatorAssertionMutation(scope),
        pending: useHomeworldLocatorAssertionPending(scope),
      }),
      { wrapper }
    )
    const hookB = renderHook(
      () => ({
        pending: useHomeworldLocatorAssertionPending(scope),
      }),
      { wrapper }
    )

    act(() => {
      hookA.result.current.mutation.mutate({
        axis: 'location',
        action: 'upsert',
        planetId: 12,
      })
    })

    await waitFor(() => {
      expect(hookA.result.current.pending).toBe(true)
      expect(hookB.result.current.pending).toBe(true)
    })
  })

  it('clears shared error after a later success on another mutation instance', async () => {
    const fail = new Error('assert failed')
    vi.mocked(postHomeworldLocatorAssertion)
      .mockRejectedValueOnce(fail)
      .mockResolvedValueOnce(emptyPayload)

    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const wrapper = createWrapper(client)

    const hookA = renderHook(() => useHomeworldLocatorAssertionMutation(scope), { wrapper })
    const hookB = renderHook(() => useHomeworldLocatorAssertionMutation(scope), { wrapper })
    const errorHook = renderHook(() => useHomeworldLocatorAssertionError(scope), { wrapper })

    await act(async () => {
      try {
        await hookA.result.current.mutateAsync({
          axis: 'location',
          action: 'upsert',
          planetId: 12,
        })
      } catch {
        // expected failure
      }
    })

    await waitFor(() => {
      expect(errorHook.result.current).toBe(fail)
    })

    await act(async () => {
      await hookB.result.current.mutateAsync({
        axis: 'location',
        action: 'upsert',
        planetId: 12,
      })
    })

    await waitFor(() => {
      expect(errorHook.result.current).toBeNull()
    })
  })

  it('surfaces the latest in-flight failure as the shared error', async () => {
    const firstFail = new Error('first fail')
    const secondFail = new Error('second fail')
    vi.mocked(postHomeworldLocatorAssertion)
      .mockRejectedValueOnce(firstFail)
      .mockRejectedValueOnce(secondFail)

    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const wrapper = createWrapper(client)

    const hookA = renderHook(() => useHomeworldLocatorAssertionMutation(scope), { wrapper })
    const hookB = renderHook(() => useHomeworldLocatorAssertionMutation(scope), { wrapper })
    const errorHook = renderHook(() => useHomeworldLocatorAssertionError(scope), { wrapper })

    await act(async () => {
      try {
        await hookA.result.current.mutateAsync({
          axis: 'location',
          action: 'upsert',
          planetId: 12,
        })
      } catch {
        // expected
      }
    })

    await waitFor(() => {
      expect(errorHook.result.current).toBe(firstFail)
    })

    await act(async () => {
      try {
        await hookB.result.current.mutateAsync({
          axis: 'location',
          action: 'upsert',
          planetId: 13,
        })
      } catch {
        // expected
      }
    })

    await waitFor(() => {
      expect(errorHook.result.current).toBe(secondFail)
    })
  })
})
