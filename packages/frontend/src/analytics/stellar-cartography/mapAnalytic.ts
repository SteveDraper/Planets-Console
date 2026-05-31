import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { appendStellarCartographyMapLayer } from './mapLayer'

export const stellarCartographyMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context, options) {
    const stellarCartography = options.stellarCartography
    if (stellarCartography == null) {
      throw new Error('Stellar Cartography map merge requires stellarCartography options')
    }
    if (data.meta?.nuIonStorms != null) {
      context.nuIonStorms = data.meta.nuIonStorms
    }
    appendStellarCartographyMapLayer({
      data,
      nodes: context.nodes,
      edges: context.edges,
      overlayCircles: context.overlayCircles,
      wormholeUnknownEntrances: context.wormholeUnknownEntrances,
      layerVisibility: stellarCartography.layerVisibility,
      settingsGates: stellarCartography.settingsGates,
      wormholeDisplayMode: stellarCartography.wormholeDisplayMode,
      starClusterDisplayMode: stellarCartography.starClusterDisplayMode,
      neutronClusterDisplayMode: stellarCartography.neutronClusterDisplayMode,
    })
  },
}
