/**
 * Scores inference NDJSON stream: runtime validation and TypeScript types.
 */

import { z } from 'zod'

export const FLEET_TORP_INPUT_STATUSES = [
  'not_applicable',
  'pending',
  'applied',
  'unavailable',
] as const

export const fleetTorpInputStatusSchema = z.enum(FLEET_TORP_INPUT_STATUSES)

export const INFERENCE_DISPLAY_STATUSES = [
  'success',
  'pending',
  'paused',
  'failure',
  'stopped',
  'skipped',
  'moderate_residual',
  'mine_score_residual',
  'uncharacterized_roster',
] as const

export const inferenceDisplayStatusSchema = z.enum(INFERENCE_DISPLAY_STATUSES)

export const PLACEHOLDER_DEPARTURE_ID = 'placeholder_departure'

const shipClassSchema = z.enum(['warship', 'freighter'])

export const unknownLossPointLeftoverSchema = z.object({
  kind: z.literal('point'),
  unexplainedMilitaryDelta2x: z.number().int(),
})

export const unknownLossBoundLeftoverSchema = z
  .object({
    kind: z.literal('unknown_loss_bound'),
    lowerBound2x: z.number().int(),
  })
  .strict()

export const unknownLossLeftoverSchema = z.discriminatedUnion('kind', [
  unknownLossPointLeftoverSchema,
  unknownLossBoundLeftoverSchema,
])

export const placeholderDepartureSchema = z.object({
  id: z.literal(PLACEHOLDER_DEPARTURE_ID),
  shipClass: shipClassSchema,
  count: z.number().int().positive(),
  counterpartyPlayerId: z.number().int().optional(),
})

const latticeSignatureBuildSchema = z.object({
  id: z.string(),
  hullId: z.number().int(),
  count: z.number().int().positive(),
  buildSlotUsage: z.number().int(),
  militaryScoreDelta2xMin: z.number().int().optional(),
  militaryScoreDelta2xMax: z.number().int().optional(),
})

export const latticeSignatureSchema = z.object({
  shipClass: shipClassSchema,
  build: latticeSignatureBuildSchema,
  departure: placeholderDepartureSchema,
})

const inferenceSolutionActionSchema = z.object({
  actionId: z.string(),
  label: z.string(),
  count: z.number().int(),
  counterpartyPlayerId: z.number().int().optional(),
})

const inferenceSolutionShipBuildSchema = z.object({
  comboId: z.string(),
  label: z.string(),
  count: z.number().int(),
  hullId: z.number().int().nullish(),
  engineId: z.number().int().nullish(),
  beamId: z.number().int().nullish(),
  torpId: z.number().int().nullish(),
  beamCount: z.number().int().nullish(),
  launcherCount: z.number().int().nullish(),
})

export const inferenceStreamSolutionPayloadSchema = z.object({
  objectiveValue: z.number(),
  actions: z.array(inferenceSolutionActionSchema),
  shipBuilds: z.array(inferenceSolutionShipBuildSchema).optional(),
  militaryScoreArithmetic: z.record(z.string(), z.unknown()).optional(),
  shipFirstFamily: z.enum(['mine_overshoot', 'ammo_top_up']).optional(),
})

const inferenceStreamPlayerScopeSchema = z.object({
  playerId: z.number().int().optional(),
})

export const inferenceStreamSolutionEventSchema = inferenceStreamPlayerScopeSchema.extend({
  type: z.literal('solution'),
  solutions: z.array(inferenceStreamSolutionPayloadSchema),
  segmentId: z.string().optional(),
  scoreboardDeltaSource: z.string().optional(),
  fleetTorpInputStatus: fleetTorpInputStatusSchema.optional(),
})

export const inferenceStreamProgressEventSchema = inferenceStreamPlayerScopeSchema.extend({
  type: z.literal('progress'),
  policyStepId: z.string().optional(),
  comboCount: z.number().int().optional(),
  heldCount: z.number().int().optional(),
  solverStatus: z.string().optional(),
  elapsedSeconds: z.number().optional(),
})

export const inferenceStreamCompleteEventSchema = inferenceStreamPlayerScopeSchema.extend({
  type: z.literal('complete'),
  status: z.string(),
  displayStatus: inferenceDisplayStatusSchema,
  summary: z.string(),
  solutionCount: z.number().int().min(0),
  isComplete: z.boolean(),
  solutions: z.array(inferenceStreamSolutionPayloadSchema).optional(),
  placeholders: z.array(z.record(z.string(), z.unknown())).optional(),
  leftover: unknownLossLeftoverSchema.optional(),
  latticeSignatures: z.array(latticeSignatureSchema).optional(),
  unexplainedMilitaryDelta2x: z.number().int().optional(),
  diagnostics: z.record(z.string(), z.unknown()).optional(),
  fleetTorpInputStatus: fleetTorpInputStatusSchema.optional(),
  fleetTorpOverlayBeliefSetTorpIds: z.array(z.number().int()).optional(),
})

export const inferenceStreamErrorEventSchema = inferenceStreamPlayerScopeSchema.extend({
  type: z.literal('error'),
  detail: z.string(),
})

export const inferenceStreamGlobalPauseEventSchema = z.object({
  type: z.literal('globalPause'),
  paused: z.boolean(),
})

export const inferenceStreamEventSchema = z.discriminatedUnion('type', [
  inferenceStreamSolutionEventSchema,
  inferenceStreamProgressEventSchema,
  inferenceStreamCompleteEventSchema,
  inferenceStreamErrorEventSchema,
  inferenceStreamGlobalPauseEventSchema,
])

export type FleetTorpInputStatus = z.infer<typeof fleetTorpInputStatusSchema>
export type InferenceDisplayStatus = z.infer<typeof inferenceDisplayStatusSchema>
export type UnknownLossLeftover = z.infer<typeof unknownLossLeftoverSchema>
export type PlaceholderDeparture = z.infer<typeof placeholderDepartureSchema>
export type LatticeSignature = z.infer<typeof latticeSignatureSchema>

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
