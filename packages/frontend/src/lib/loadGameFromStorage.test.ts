import { describe, expect, it, vi } from 'vitest'
import { LOGIN_REQUIRED_FOR_GAME_SELECTION, SPECTATOR_VIEWPOINT_NAME } from './gameInfoShell'
import { loadGameFromStorage } from './loadGameFromStorage'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    fetchStoredGameInfo: vi.fn(),
    fetchStoredTurnPerspectives: vi.fn(),
  }
})

import { fetchStoredGameInfo, fetchStoredTurnPerspectives } from '../api/bff'

const sampleGameInfo = {
  game: { id: 628580, turn: 111, name: 'Test Sector' },
  settings: { turn: 111, name: 'Test Sector' },
  players: [{ id: 1, username: 'alpha' }, { id: 2, username: 'beta' }],
} as const

describe('loadGameFromStorage', () => {
  it('returns stored game info and first perspective with turn data', async () => {
    vi.mocked(fetchStoredGameInfo).mockResolvedValue(sampleGameInfo as never)
    vi.mocked(fetchStoredTurnPerspectives).mockResolvedValue({ perspectives: [2] })

    const result = await loadGameFromStorage('628580')

    expect(result.turn).toBe(111)
    expect(result.storedPerspectives).toEqual([2])
    expect(result.defaultViewpointName).toBe('beta')
    expect(fetchStoredTurnPerspectives).toHaveBeenCalledWith('628580', 111)
  })

  it('defaults to spectator when only pseudo perspective 0 is stored', async () => {
    vi.mocked(fetchStoredGameInfo).mockResolvedValue(sampleGameInfo as never)
    vi.mocked(fetchStoredTurnPerspectives).mockResolvedValue({ perspectives: [0] })

    const result = await loadGameFromStorage('628580')

    expect(result.storedPerspectives).toEqual([0])
    expect(result.defaultViewpointName).toBe(SPECTATOR_VIEWPOINT_NAME)
  })

  it('throws login required when game info is missing from storage', async () => {
    vi.mocked(fetchStoredGameInfo).mockRejectedValue(
      new Error("Document not found: 'games/628580/info'")
    )

    await expect(loadGameFromStorage('628580')).rejects.toThrow(
      LOGIN_REQUIRED_FOR_GAME_SELECTION
    )
  })

  it('rethrows operational failures from fetchStoredGameInfo', async () => {
    const serverError = new Error('Internal Server Error (GET /bff/games/628580/info)')
    vi.mocked(fetchStoredGameInfo).mockRejectedValue(serverError)

    await expect(loadGameFromStorage('628580')).rejects.toThrow(serverError.message)
  })

  it('throws login required when no perspective has the current turn stored', async () => {
    vi.mocked(fetchStoredGameInfo).mockResolvedValue(sampleGameInfo as never)
    vi.mocked(fetchStoredTurnPerspectives).mockResolvedValue({ perspectives: [] })

    await expect(loadGameFromStorage('628580')).rejects.toThrow(
      LOGIN_REQUIRED_FOR_GAME_SELECTION
    )
  })
})
