import { applyFutureIonStormOverlayPositions } from '../../lib/cartography/futureTurnIonStorms'
import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { appendStellarCartographyMapLayer } from './mapLayer'

export const stellarCartographyMapAnalytic: MapAnalyticRegistration = {
  requiresLiveMapContext: true,
  mergeLayer(data, context, options) {
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
    const forwardTurns = options.stellarCartographyFutureTurnOffset ?? 0
    if (forwardTurns > 0) {
      const shifted = applyFutureIonStormOverlayPositions(context.overlayCircles, forwardTurns)
      context.overlayCircles.length = 0
      context.overlayCircles.push(...shifted)
    }
  },
}
