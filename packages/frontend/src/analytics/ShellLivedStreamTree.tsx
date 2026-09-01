import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import {
  shellLivedStreamRegistrations,
  type ShellLivedStreamSlot,
} from './shellAnalyticRegistry'

function ShellLivedStreamMount({
  stream,
  analyticScope,
  enabled,
  children,
}: {
  stream: ShellLivedStreamSlot
  analyticScope: AnalyticShellScope | null
  enabled: boolean
  children: ReactNode
}) {
  const session = stream.hook(analyticScope, enabled)
  const Provider = stream.Provider
  return <Provider {...session}>{children}</Provider>
}

/**
 * Mounts every shell-lived stream registration above view mode so toggling
 * tabular vs map does not tear the session down.
 */
export function ShellLivedStreamTree({
  analyticScope,
  enabledAnalyticIds,
  streamEnabled,
  children,
}: {
  analyticScope: AnalyticShellScope | null
  enabledAnalyticIds: string[]
  streamEnabled: boolean
  children: ReactNode
}) {
  return shellLivedStreamRegistrations().reduceRight((node, { analyticId, stream }) => {
    return (
      <ShellLivedStreamMount
        stream={stream}
        analyticScope={analyticScope}
        enabled={streamEnabled && enabledAnalyticIds.includes(analyticId)}
      >
        {node}
      </ShellLivedStreamMount>
    )
  }, children)
}
