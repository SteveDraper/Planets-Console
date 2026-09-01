import { ConnectionsMapTile } from './ConnectionsMapTile'
import { appendConnectionsMapQueryParamsFromStore } from './queryParams'
import type { ShellAnalyticRegistration } from '../shellAnalyticRegistry'

export const connectionsShellAnalytic: ShellAnalyticRegistration = {
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
  queryParams: { appendMap: appendConnectionsMapQueryParamsFromStore },
}
