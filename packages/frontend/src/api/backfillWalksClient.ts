import { bffRequest } from './bff'
import { throwBffHttpErrorFromResponse } from './bffHttpError'
import type { paths } from './schema-games'

const BACKFILL_WALKS_STOP_ROUTE = '/games/{game_id}/backfill-walks/stop' satisfies keyof paths

/** Stateless stop of every accepted Backfill earlier turns walk in a game the shell left (204). */
export async function postBackfillWalksStop(gameId: string): Promise<void> {
  const path = `/bff${BACKFILL_WALKS_STOP_ROUTE.replace('{game_id}', encodeURIComponent(gameId))}`
  const endpointLabel = `POST ${path}`
  const r = await bffRequest(path, { method: 'POST' }, endpointLabel)
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
}
