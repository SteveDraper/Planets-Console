import { VisibilityMapTile } from './VisibilityMapTile'
import type { ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const visibilityShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    const supportsMode = ctx.catalogItem.supportsMap
    return (
      <VisibilityMapTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
      />
    )
  },
}
