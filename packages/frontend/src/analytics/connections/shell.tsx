import { ConnectionsMapTile } from './ConnectionsMapTile'
import type { ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const connectionsShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    const supportsMode = ctx.catalogItem.supportsMap
    return (
      <ConnectionsMapTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
      />
    )
  },
}
