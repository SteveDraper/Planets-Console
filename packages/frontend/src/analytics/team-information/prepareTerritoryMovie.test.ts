import { afterEach, describe, expect, it, vi } from 'vitest'
import { ensureTurnData, fetchTerritoryMovie } from '../../api/bff'
import { openTerritoryMovieWindow, prepareTerritoryMovie } from './prepareTerritoryMovie'

vi.mock('../../api/bff', () => ({
  ensureTurnData: vi.fn(),
  fetchTerritoryMovie: vi.fn(),
}))

const payload = {
  turn: 3,
  rectangle: { left: 0, bottom: 0, width: 10, height: 10 },
  rings: 'RINGSBLOB',
  planets: 'PLANETSBLOB',
  players: [{ id: 1, name: 'Ada' }],
  teams: [{ id: 4, name: null }],
}

describe('prepareTerritoryMovie', () => {
  afterEach(() => {
    vi.mocked(ensureTurnData).mockReset()
    vi.mocked(fetchTerritoryMovie).mockReset()
  })

  it('ensures every host turn through the game turn, then returns one document', async () => {
    vi.mocked(ensureTurnData).mockResolvedValue({
      ready: true,
      turnUsernamesByPlayerId: new Map(),
      turnRelations: [],
    })
    vi.mocked(fetchTerritoryMovie).mockResolvedValue(payload)
    const html = await prepareTerritoryMovie({
      gameId: '628580',
      perspective: 2,
      gameTurn: 3,
      username: ' ada ',
    })
    expect(vi.mocked(ensureTurnData).mock.calls.map((call) => call[1])).toEqual([
      { turn: 1, perspective: 2, username: 'ada' },
      { turn: 2, perspective: 2, username: 'ada' },
      { turn: 3, perspective: 2, username: 'ada' },
    ])
    expect(ensureTurnData).toHaveBeenCalledTimes(3)
    expect(fetchTerritoryMovie).toHaveBeenCalledWith('628580', 2)
    expect(html).toContain('RINGSBLOB')
    expect(html).toContain('PLANETSBLOB')
    expect(html).toContain('Back to turn 1')
    expect(html).toContain('#8fff00')
    expect(html).toContain('#fff48f')
    expect(html).toContain('#ab8700')
  })

  it('stops before the payload when an ensure fails', async () => {
    vi.mocked(ensureTurnData)
      .mockResolvedValueOnce({
        ready: true,
        turnUsernamesByPlayerId: new Map(),
        turnRelations: [],
      })
      .mockRejectedValueOnce(new Error('missing turn 2'))
    await expect(
      prepareTerritoryMovie({
        gameId: '628580',
        perspective: 1,
        gameTurn: 4,
        username: 'ada',
      })
    ).rejects.toThrow('missing turn 2')
    expect(fetchTerritoryMovie).not.toHaveBeenCalled()
    expect(ensureTurnData).toHaveBeenCalledTimes(2)
  })

  it('does not build a document when the payload fails', async () => {
    vi.mocked(ensureTurnData).mockResolvedValue({
      ready: true,
      turnUsernamesByPlayerId: new Map(),
      turnRelations: [],
    })
    vi.mocked(fetchTerritoryMovie).mockRejectedValue(new Error('payload failed'))
    await expect(
      prepareTerritoryMovie({
        gameId: '628580',
        perspective: 1,
        gameTurn: 1,
        username: 'ada',
      })
    ).rejects.toThrow('payload failed')
  })

  it('rejects a missing game turn before ensuring', async () => {
    await expect(
      prepareTerritoryMovie({
        gameId: '628580',
        perspective: 1,
        gameTurn: 0,
        username: 'ada',
      })
    ).rejects.toThrow(/current turn/)
    expect(ensureTurnData).not.toHaveBeenCalled()
  })
})

describe('openTerritoryMovieWindow', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  function installBlobUrl(): void {
    if (typeof URL.createObjectURL !== 'function') {
      Object.defineProperty(URL, 'createObjectURL', {
        configurable: true,
        writable: true,
        value: () => 'blob:unset',
      })
    }
    if (typeof URL.revokeObjectURL !== 'function') {
      Object.defineProperty(URL, 'revokeObjectURL', {
        configurable: true,
        writable: true,
        value: () => {},
      })
    }
  }

  it('revokes the blob url only after the window closes', () => {
    installBlobUrl()
    vi.useFakeTimers()
    vi.spyOn(URL, 'createObjectURL').mockImplementation((value) => {
      expect(value).toBeInstanceOf(Blob)
      expect((value as Blob).type).toBe('text/html')
      return 'blob:movie'
    })
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const opened = { closed: false }
    vi.spyOn(window, 'open').mockReturnValue(opened as Window)
    openTerritoryMovieWindow('<html></html>')
    expect(revoke).not.toHaveBeenCalled()
    opened.closed = true
    vi.advanceTimersByTime(1000)
    expect(revoke).toHaveBeenCalledWith('blob:movie')
  })

  it('does not leave a url when the browser blocks the window', () => {
    installBlobUrl()
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:movie')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(window, 'open').mockReturnValue(null)
    expect(() => openTerritoryMovieWindow('<html></html>')).toThrow(/blocked/)
    expect(revoke).toHaveBeenCalledWith('blob:movie')
  })
})
