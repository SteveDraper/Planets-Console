import { StellarCartographyMapTile } from './StellarCartographyMapTile'
import type { ShellAnalyticRegistration } from '../shellAnalyticRegistry'

export const stellarCartographyShellAnalytic: ShellAnalyticRegistration = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    const supportsMode = ctx.catalogItem.supportsMap
    return (
      <StellarCartographyMapTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
        turnDataReady={ctx.turnDataReady}
        analyticScope={ctx.analyticScope}
      />
    )
  },
}
