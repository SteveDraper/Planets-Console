import type { ReactNode } from 'react'
import { GenericAnalyticCheckbox } from './GenericAnalyticCheckbox'
import {
  analyticSupportsViewMode,
  shellAnalyticRegistrationFor,
  type ShellAnalyticSidebarContext,
} from './shellAnalyticRegistry'

/** Dispatch sidebar chrome: custom factory, or generic checkbox when missing/null. */
export function renderShellAnalyticSidebar(ctx: ShellAnalyticSidebarContext): ReactNode {
  const custom = shellAnalyticRegistrationFor(ctx.catalogItem.id)?.renderSidebar?.(ctx)
  if (custom != null) {
    return custom
  }
  const supportsMode = analyticSupportsViewMode(ctx.catalogItem, ctx.viewMode)
  return (
    <GenericAnalyticCheckbox
      name={ctx.catalogItem.name}
      enabled={ctx.enabled}
      supportsMode={supportsMode}
      depressed={ctx.enabled && supportsMode}
      onToggle={ctx.onToggle}
    />
  )
}
