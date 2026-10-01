import type { ReactNode } from 'react'
import { AnalyticSidebarTile } from './AnalyticSidebarTile'
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
  return <AnalyticSidebarTile {...sidebarTileChrome(ctx)} />
}
