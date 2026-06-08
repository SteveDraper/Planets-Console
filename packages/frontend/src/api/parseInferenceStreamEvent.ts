import {
  formatInferenceStreamValidationError,
  inferenceStreamEventSchema,
  type InferenceStreamEvent,
} from './inferenceStreamEventSchema'

export type { InferenceStreamEvent }

export function parseInferenceStreamEvent(line: string): InferenceStreamEvent | null {
  const trimmed = line.trim()
  if (!trimmed) {
    return null
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error('Inference stream returned invalid JSON.')
  }

  const result = inferenceStreamEventSchema.safeParse(parsed)
  if (!result.success) {
    throw new Error(formatInferenceStreamValidationError(result.error))
  }

  return result.data
}
