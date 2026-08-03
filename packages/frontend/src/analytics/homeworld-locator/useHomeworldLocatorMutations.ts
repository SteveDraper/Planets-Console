/**
 * TanStack mutations for homeworld assert / revoke / refresh (#37).
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
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

export function useHomeworldLocatorAssertionMutation(scope: AnalyticShellScope | null) {
  const queryClient = useQueryClient()
  return useMutation({
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
