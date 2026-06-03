/**
 * Consume a response body as newline-delimited JSON, invoking onLine for each
 * complete line and once more for any trailing bytes after the stream ends.
 */
export async function readNdjsonStream(
  body: ReadableStream<Uint8Array>,
  onLine: (line: string) => void | Promise<void>
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      await onLine(line)
    }
  }

  await onLine(buffer)
}
