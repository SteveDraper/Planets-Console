import type { ComponentType, ReactNode } from 'react'
import type { AnalyticShellScope } from '../api/bff'

export type ShellLivedStreamMountProps = {
  analyticScope: AnalyticShellScope | null
  enabled: boolean
  children: ReactNode
}

/**
 * Shell-lived table stream: `hook` session props match `Provider` props (minus children).
 * Construct with `shellLivedStream` so the registry mounts a typed pair.
 */
export type ShellLivedStreamSlot<TSession extends object> = {
  lifetime: 'shell'
  hook: (analyticScope: AnalyticShellScope | null, enabled: boolean) => TSession
  Provider: ComponentType<TSession & { children: ReactNode }>
}

/** Registry-facing shell-lived stream; session pairing is closed over by `Mount`. */
export type ShellLivedStreamMountSlot = {
  lifetime: 'shell'
  Mount: ComponentType<ShellLivedStreamMountProps>
}

export type TileLivedStreamSlot = {
  lifetime: 'tile'
}

export type ShellAnalyticStreamSlot = ShellLivedStreamMountSlot | TileLivedStreamSlot

/**
 * Bind a hook/Provider pair whose session type stays inside `Mount`.
 * The returned object still exposes `lifetime`, `hook`, and `Provider`.
 */
export function shellLivedStream<TSession extends object>({
  hook,
  Provider,
}: {
  hook: (analyticScope: AnalyticShellScope | null, enabled: boolean) => TSession
  Provider: ComponentType<TSession & { children: ReactNode }>
}): ShellLivedStreamSlot<TSession> & ShellLivedStreamMountSlot {
  function Mount({ analyticScope, enabled, children }: ShellLivedStreamMountProps) {
    const session = hook(analyticScope, enabled)
    return <Provider {...session}>{children}</Provider>
  }
  return { lifetime: 'shell', hook, Provider, Mount }
}
