import { describe, expect, it, vi } from 'vitest'
import * as bff from '../../api/bff'
import {
  TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
  connectTableInferenceStream,
} from './tableInferenceStreamConnect'

const scope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

describe('connectTableInferenceStream', () => {
  it('retries when the scope-level stream conflict error is returned', async () => {
    const fetchSpy = vi
      .spyOn(bff, 'fetchScoresTableInferenceStream')
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'error',
          detail: TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
        })
      })
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'ok',
          solutionCount: 1,
          isComplete: true,
        })
      })

    const events: unknown[] = []
    const controller = new AbortController()
    const result = await connectTableInferenceStream(scope, [8], {
      signal: controller.signal,
      onEvent: (event) => {
        events.push(event)
      },
    })

    expect(result).toBe('ok')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(events).toHaveLength(1)
  })
})
