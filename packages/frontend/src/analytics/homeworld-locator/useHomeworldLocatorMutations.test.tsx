import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { postHomeworldLocatorAssertion } from './api'
import {
  homeworldLocatorAssertionMutationKey,
  useHomeworldLocatorAssertionMutation,
  useHomeworldLocatorAssertionPending,
} from './useHomeworldLocatorMutations'

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
})
