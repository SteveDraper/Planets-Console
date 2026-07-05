import { describe, expect, it, vi } from 'vitest'
import * as bff from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import {
  connectFleetTableStream,
  connectFleetTableStreamUntilComplete,
} from './fleetTableStreamConnect'

const scope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

describe('connectFleetTableStream', () => {
  it('reconnects when the stream ends before every player is complete', async () => {
    const fetchSpy = vi
      .spyOn(bff, 'fetchFleetTableStream')
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          isFinal: true,
          summary: 'cached',
        })
      })
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          isFinal: true,
          summary: 'cached replay',
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 6,
          isFinal: true,
          summary: 'after reconnect',
        })
      })

    const completedPlayerIds = new Set<number>()
    const controller = new AbortController()
    const result = await connectFleetTableStreamUntilComplete(scope, [8, 6], {
      signal: controller.signal,
      onEvent: (event) => {
        if (event.type === 'complete' && event.playerId != null) {
          completedPlayerIds.add(event.playerId)
        }
      },
      hasPendingPlayers: () => [8, 6].some((playerId) => !completedPlayerIds.has(playerId)),
    })

    expect(result).toBe('ok')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(completedPlayerIds).toEqual(new Set([8, 6]))
  })
})
