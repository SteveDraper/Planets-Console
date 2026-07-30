import { describe, it, expect, vi, afterEach } from 'vitest'
import { BffHttpError } from './bffHttpError'
import { fetchLayoutPriorReports } from './bffLayoutPriorDiagnostics'

const scope = { gameId: '7', perspective: 3, turn: 12 }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchLayoutPriorReports', () => {
  it('throws BffHttpError carrying status and server detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: 'Layout prior evidence is not ready' }), {
            status: 503,
          })
        )
      )
    )
    const thrown = await fetchLayoutPriorReports(scope).catch((e: unknown) => e)
    expect(thrown).toBeInstanceOf(BffHttpError)
    expect((thrown as BffHttpError).status).toBe(503)
    expect((thrown as BffHttpError).detail).toBe('Layout prior evidence is not ready')
  })

  it('defaults missing collections to empty', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ shell: { gameId: 7, perspective: 3, turn: 12 }, reports: [] }),
            { status: 200 }
          )
        )
      )
    )
    const result = await fetchLayoutPriorReports(scope)
    expect(result.shell).toEqual(scope)
    expect(result.evidenceRefineReports).toEqual([])
    expect(result.evidenceRefineSummary).toEqual({})
    expect(result.baselineReports).toEqual([])
    expect(result.ensureFailures).toEqual([])
  })
})
