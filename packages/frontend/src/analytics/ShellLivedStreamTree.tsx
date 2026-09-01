import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import { shellLivedStreamRegistrations } from './shellAnalyticRegistry'

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
    const Mount = stream.Mount
    return (
      <Mount
        analyticScope={analyticScope}
        enabled={streamEnabled && enabledAnalyticIds.includes(analyticId)}
      >
        {node}
      </Mount>
    )
  }, children)
}
