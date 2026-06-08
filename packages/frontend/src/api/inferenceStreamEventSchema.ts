/**
 * Scores inference NDJSON stream: runtime validation and TypeScript types.
 */

import { z } from 'zod'

const inferenceSolutionActionSchema = z.object({
  actionId: z.string(),
  label: z.string(),
  count: z.number().int(),
})

const inferenceSolutionShipBuildSchema = z.object({
  comboId: z.string(),
  label: z.string(),
  count: z.number().int(),
  hullId: z.number().int().optional(),
  engineId: z.number().int().optional(),
  beamId: z.number().int().optional(),
  torpId: z.number().int().optional(),
  beamCount: z.number().int().optional(),
  launcherCount: z.number().int().optional(),
})

export const inferenceStreamSolutionPayloadSchema = z.object({
  objectiveValue: z.number(),
  actions: z.array(inferenceSolutionActionSchema),
  shipBuilds: z.array(inferenceSolutionShipBuildSchema).optional(),
  militaryScoreArithmetic: z.record(z.string(), z.unknown()).optional(),
})

export const inferenceStreamSolutionEventSchema = z.object({
  type: z.literal('solution'),
  solution: inferenceStreamSolutionPayloadSchema,
})

export const inferenceStreamProgressEventSchema = z.object({
  type: z.literal('progress'),
  policyStepId: z.string().optional(),
  comboCount: z.number().int().optional(),
  heldCount: z.number().int().optional(),
  solverStatus: z.string().optional(),
  elapsedSeconds: z.number().optional(),
})

export const inferenceStreamCompleteEventSchema = z.object({
  type: z.literal('complete'),
  status: z.string(),
  summary: z.string(),
  solutionCount: z.number().int().min(0),
  isComplete: z.boolean(),
  diagnostics: z.record(z.string(), z.unknown()).optional(),
})

export const inferenceStreamErrorEventSchema = z.object({
  type: z.literal('error'),
  detail: z.string(),
})

export const inferenceStreamEventSchema = z.discriminatedUnion('type', [
  inferenceStreamSolutionEventSchema,
  inferenceStreamProgressEventSchema,
  inferenceStreamCompleteEventSchema,
  inferenceStreamErrorEventSchema,
])

export type InferenceStreamSolutionPayload = z.infer<typeof inferenceStreamSolutionPayloadSchema>
export type InferenceStreamEvent = z.infer<typeof inferenceStreamEventSchema>
export type InferenceStreamCompleteEvent = z.infer<typeof inferenceStreamCompleteEventSchema>

export function formatInferenceStreamValidationError(error: z.ZodError): string {
  const issue = error.issues[0]
  if (!issue) {
    return 'Inference stream event has an invalid shape.'
  }
  if (issue.code === 'invalid_union_discriminator') {
    return 'Inference stream returned unknown event type.'
  }
  if (issue.path.includes('detail')) {
    return 'Inference stream error event has an invalid shape.'
  }
  return 'Inference stream event has an invalid shape.'
}
