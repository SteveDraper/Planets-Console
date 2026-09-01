import { appendConnectionsMapQueryParams } from './api'
import { useConnectionsMapParamsStore } from './connectionsMapParamsStore'

/** Append Connections map query params from the ephemeral Zustand store. */
export function appendConnectionsMapQueryParamsFromStore(params: URLSearchParams): void {
  appendConnectionsMapQueryParams(
    params,
    useConnectionsMapParamsStore.getState().connectionsMapParams
  )
}
