import { throwBffHttpErrorFromResponse } from './bffHttpError'
import { sendBffRequest } from './bffSend'
import type { paths } from './schema-games'

const BACKFILL_WALKS_STOP_ROUTE = '/games/{game_id}/backfill-walks/stop' satisfies keyof paths

/**
 * How long a stop may take before it is aborted. Every request for its game waits on the stop,
 * so the bound keeps a hung stop from holding them indefinitely.
 */
export const BACKFILL_WALKS_STOP_TIMEOUT_MS = 5_000

/**
 * Stateless stop of every accepted Backfill earlier turns walk in a game the shell left (204).
 * It is sent without waiting for a pending stop, because it is the request that stop chains wait on.
 * It rejects when it fails or takes longer than {@link BACKFILL_WALKS_STOP_TIMEOUT_MS}.
 */
export async function postBackfillWalksStop(gameId: string): Promise<void> {
  const path = `/bff${BACKFILL_WALKS_STOP_ROUTE.replace('{game_id}', encodeURIComponent(gameId))}`
  const endpointLabel = `POST ${path}`
  const r = await sendBffRequest(
    path,
    { method: 'POST', signal: AbortSignal.timeout(BACKFILL_WALKS_STOP_TIMEOUT_MS) },
    endpointLabel
  )
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
}
