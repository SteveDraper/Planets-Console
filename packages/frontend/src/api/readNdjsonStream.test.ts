import { describe, it, expect, vi } from 'vitest'
import { readNdjsonStream } from './readNdjsonStream'

function ndjsonStreamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

describe('readNdjsonStream', () => {
  it('invokes onLine for each complete line and trailing bytes without a final newline', async () => {
    const lines: string[] = []
    await readNdjsonStream(
      ndjsonStreamFromChunks(['{"a":1}\n{"b":', '2}\n{"c":3}']),
      (line) => {
        lines.push(line)
      }
    )
    expect(lines).toEqual(['{"a":1}', '{"b":2}', '{"c":3}'])
  })

  it('buffers a line split across multiple chunks', async () => {
    const lines: string[] = []
    await readNdjsonStream(
      ndjsonStreamFromChunks(['hel', 'lo\nwo', 'rld']),
      (line) => {
        lines.push(line)
      }
    )
    expect(lines).toEqual(['hello', 'world'])
  })

  it('still delivers trailing buffer when stream ends on a newline', async () => {
    const lines: string[] = []
    await readNdjsonStream(ndjsonStreamFromChunks(['only\n']), (line) => {
      lines.push(line)
    })
    expect(lines).toEqual(['only', ''])
  })

  it('awaits async onLine handlers in order', async () => {
    const order: number[] = []
    await readNdjsonStream(ndjsonStreamFromChunks(['1\n2\n3']), async (line) => {
      order.push(Number(line))
      await Promise.resolve()
    })
    expect(order).toEqual([1, 2, 3])
  })

  it('propagates errors from onLine', async () => {
    const onLine = vi.fn(() => {
      throw new Error('parse failed')
    })
    await expect(
      readNdjsonStream(ndjsonStreamFromChunks(['bad\n']), onLine)
    ).rejects.toThrow('parse failed')
    expect(onLine).toHaveBeenCalledTimes(1)
  })
})
