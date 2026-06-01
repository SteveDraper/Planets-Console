import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { appendStellarCartographyMapLayer } from './mapLayer'

export const stellarCartographyMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context) {
    if (data.meta?.nuIonStorms != null) {
      context.nuIonStorms = data.meta.nuIonStorms
    }
    appendStellarCartographyMapLayer({
      data,
      nodes: context.nodes,
      edges: context.edges,
      overlayCircles: context.overlayCircles,
      wormholeUnknownEntrances: context.wormholeUnknownEntrances,
    })
  },
}
