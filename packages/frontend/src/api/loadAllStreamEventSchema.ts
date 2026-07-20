/**
 * Load-all NDJSON stream: runtime validation and TypeScript types (wire contract matches BFF OpenAPI).
 */

import { z } from 'zod'

const nonNegativeInt = z
  .number({ message: 'must be a number' })
  .int()
  .min(0, { message: 'must be a non-negative integer' })

export const loadAllProgressFieldsSchema = z.object({
  phase: z.enum(['download', 'import', 'final_turn']),
  perspective: nonNegativeInt,
  perspective_total: nonNegativeInt,
  turn: nonNegativeInt,
  turn_total: nonNegativeInt,
  message: z.string(),
})

export const loadAllTurnsResponseSchema = z.object({
  game_id: z.number().int({ message: 'must be an integer' }),
  is_game_finished: z.boolean(),
  turns_written: nonNegativeInt,
  turns_skipped: nonNegativeInt,
  perspectives_touched: z.array(z.number().int()).optional(),
  final_turn_load_failures: z.array(z.number().int()).optional(),
})

export const loadAllStreamProgressEventSchema = loadAllProgressFieldsSchema.extend({
  type: z.literal('progress'),
})

export const loadAllStreamCompleteEventSchema = z.object({
  type: z.literal('complete'),
  result: loadAllTurnsResponseSchema,
})

export const loadAllStreamErrorEventSchema = z.object({
  type: z.literal('error'),
  detail: z.string(),
  /** HTTP status that would apply if this were a non-stream failure (e.g. 401). */
  http_error: z.number().int(),
})

export const loadAllStreamEventSchema = z.discriminatedUnion('type', [
  loadAllStreamProgressEventSchema,
  loadAllStreamCompleteEventSchema,
  loadAllStreamErrorEventSchema,
])

export type LoadAllProgressUpdate = z.infer<typeof loadAllProgressFieldsSchema>
export type LoadAllTurnsResponse = z.infer<typeof loadAllTurnsResponseSchema>
export type LoadAllStreamEvent = z.infer<typeof loadAllStreamEventSchema>

function fieldLabel(path: (string | number)[]): string {
  if (path.length === 0) {
    return 'event'
  }
  if (path[0] === 'result' && path.length > 1) {
    return `result.${String(path[1])}`
  }
  return String(path[path.length - 1])
}

/** Map Zod failures to stable messages consumed by the shell and tests. */
export function formatLoadAllStreamValidationError(error: z.ZodError): string {
  const issue = error.issues[0]
  if (!issue) {
    return 'Load-all stream event has an invalid shape.'
  }

  if (issue.code === 'invalid_union_discriminator') {
    return 'Load-all stream returned unknown event type.'
  }

  const label = fieldLabel(issue.path)

  if (issue.path[0] === 'result') {
    if (label === 'result.game_id') {
      return 'Load-all stream complete event result.game_id must be an integer.'
    }
    if (label.startsWith('result.')) {
      return `Load-all stream complete event field ${label.replace('result.', '')} must be an array of integers.`
    }
  }

  if (
    label === 'perspective' ||
    label === 'perspective_total' ||
    label === 'turn' ||
    label === 'turn_total'
  ) {
    return `Load-all stream progress event field ${label} must be a non-negative integer.`
  }

  if (issue.path.includes('message') || issue.path.includes('phase')) {
    return 'Load-all stream progress event has an invalid shape.'
  }

  if (issue.path.includes('detail') || issue.path.includes('http_error')) {
    return 'Load-all stream error event has an invalid shape.'
  }

  if (issue.path.includes('result')) {
    return 'Load-all stream complete event has an invalid result shape.'
  }

  if (issue.path.includes('type')) {
    return 'Load-all stream event is missing a type field.'
  }

  return 'Load-all stream event has an invalid shape.'
}
