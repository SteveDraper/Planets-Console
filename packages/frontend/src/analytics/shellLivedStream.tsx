import type { ComponentType, ReactNode } from 'react'
import type { AnalyticShellScope } from '../api/bff'

export type ShellLivedStreamMountProps = {
  analyticScope: AnalyticShellScope | null
  enabled: boolean
  children: ReactNode
}

type ShellLivedHook<TSession> = (
  analyticScope: AnalyticShellScope | null,
  enabled: boolean,
) => TSession

/**
 * Shell-lived table stream: `hook` session props match `Provider` props (minus children).
 * Construct with `shellLivedStream` so the registry mounts a typed pair.
 */
export type ShellLivedStreamSlot<TSession extends object> = {
  lifetime: 'shell'
  hook: ShellLivedHook<TSession>
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

type SessionStream<TSession extends object> = ShellLivedStreamSlot<TSession> &
  ShellLivedStreamMountSlot

type EffectStream = ShellLivedStreamMountSlot & {
  hook: ShellLivedHook<undefined>
}

/**
 * Bind a hook to a shell-lived Mount.
 * Pass `Provider` when descendants read the hook session. Omit it when the hook
 * only performs side effects; Mount still calls the hook.
 * A no-session hook returns `undefined`, which keeps `Provider` required
 * when the hook returns a session.
 */
export function shellLivedStream<TSession extends object>(args: {
  hook: ShellLivedHook<TSession>
  Provider: ComponentType<TSession & { children: ReactNode }>
}): SessionStream<TSession>
export function shellLivedStream(args: {
  hook: ShellLivedHook<undefined>
}): EffectStream
export function shellLivedStream<TSession extends object>(
  args:
    | {
        hook: ShellLivedHook<TSession>
        Provider: ComponentType<TSession & { children: ReactNode }>
      }
    | {
        hook: ShellLivedHook<undefined>
      },
): SessionStream<TSession> | EffectStream {
  if ('Provider' in args) {
    const { hook, Provider } = args
    function Mount({ analyticScope, enabled, children }: ShellLivedStreamMountProps) {
      const session = hook(analyticScope, enabled)
      return <Provider {...session}>{children}</Provider>
    }
    return { lifetime: 'shell', hook, Provider, Mount }
  }
  const { hook } = args
  function Mount({ analyticScope, enabled, children }: ShellLivedStreamMountProps) {
    hook(analyticScope, enabled)
    return children
  }
  return { lifetime: 'shell', hook, Mount }
}
