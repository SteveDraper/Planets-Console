import type { ReactNode } from 'react'
import { GenericAnalyticCheckbox } from './GenericAnalyticCheckbox'
import {
  shellAnalyticRegistrationFor,
  sidebarTileChrome,
  type ShellAnalyticSidebarContext,
} from './shellAnalyticRegistry'

/** Dispatch sidebar chrome: custom factory, or generic checkbox when missing/null. */
export function renderShellAnalyticSidebar(ctx: ShellAnalyticSidebarContext): ReactNode {
  const custom = shellAnalyticRegistrationFor(ctx.catalogItem.id)?.renderSidebar?.(ctx)
  if (custom != null) {
    return custom
  }
  return <GenericAnalyticCheckbox {...sidebarTileChrome(ctx)} />
}
