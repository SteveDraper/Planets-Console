/**
 * TanStack mutations for homeworld assert / revoke / refresh (#37).
 */

import {
  useIsMutating,
  useMutation,
  useMutationState,
  useQueryClient,
} from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import {
  postHomeworldLocatorAssertion,
  postHomeworldLocatorRefresh,
  type HomeworldAssertionRequest,
} from './api'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import type { HomeworldLocatorPayload } from './wireSchema'

async function invalidateHomeworldQueries(
  queryClient: ReturnType<typeof useQueryClient>
): Promise<void> {
  await queryClient.invalidateQueries({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID],
  })
}

/** Shared across panel and map menu so pending/errors observe the same in-flight assert. */
export function homeworldLocatorAssertionMutationKey(scope: AnalyticShellScope | null) {
  return ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'assertion', scope] as const
}

export function useHomeworldLocatorAssertionPending(scope: AnalyticShellScope | null): boolean {
  return useIsMutating({ mutationKey: homeworldLocatorAssertionMutationKey(scope) }) > 0
}

export function useHomeworldLocatorAssertionError(scope: AnalyticShellScope | null): unknown {
  const errors = useMutationState({
    filters: {
      mutationKey: homeworldLocatorAssertionMutationKey(scope),
      status: 'error',
    },
    select: (mutation) => mutation.state.error,
  })
  return errors.at(-1) ?? null
}

export function useHomeworldLocatorAssertionMutation(scope: AnalyticShellScope | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: homeworldLocatorAssertionMutationKey(scope),
    mutationFn: async (body: HomeworldAssertionRequest): Promise<HomeworldLocatorPayload> => {
      if (scope == null) {
        throw new Error('Homeworld assertion requires analytic scope')
      }
      return postHomeworldLocatorAssertion(scope, body)
    },
    onSuccess: async () => {
      await invalidateHomeworldQueries(queryClient)
    },
  })
}

export function useHomeworldLocatorRefreshMutation(scope: AnalyticShellScope | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<HomeworldLocatorPayload> => {
      if (scope == null) {
        throw new Error('Homeworld refresh requires analytic scope')
      }
      return postHomeworldLocatorRefresh(scope)
    },
    onSuccess: async () => {
      await invalidateHomeworldQueries(queryClient)
    },
  })
}
