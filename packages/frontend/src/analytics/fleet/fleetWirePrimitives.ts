import { z } from 'zod'

const fleetFieldKnownSchema = z.object({
  kind: z.literal('known'),
  value: z.union([z.number(), z.string(), z.boolean()]),
})

const fleetFieldUnknownSchema = z.object({
  kind: z.literal('unknown'),
})

const fleetFieldBoundedSchema = z.object({
  kind: z.literal('bounded'),
  operator: z.enum(['lte', 'gte', 'lt', 'gt', 'eq']),
  value: z.number(),
})

const fleetFieldOptionsSchema = z.object({
  kind: z.literal('options'),
  values: z.array(z.union([z.number(), z.string()])).min(1),
})

const fleetFieldRegionStarbaseCoordSchema = z.object({
  x: z.number().int(),
  y: z.number().int(),
})

const fleetFieldRegionSchema = z.object({
  kind: z.literal('region'),
  planetIds: z.array(z.number().int()).optional(),
  starbaseCoords: z.array(fleetFieldRegionStarbaseCoordSchema).optional(),
  overlayId: z.string().optional(),
})

function regionHasLocator(region: z.infer<typeof fleetFieldRegionSchema>): boolean {
  return (
    (region.planetIds !== undefined && region.planetIds.length > 0) ||
    (region.starbaseCoords !== undefined && region.starbaseCoords.length > 0) ||
    (region.overlayId !== undefined && region.overlayId.length > 0)
  )
}

export const fleetFieldConstraintSchema = z
  .discriminatedUnion('kind', [
    fleetFieldKnownSchema,
    fleetFieldUnknownSchema,
    fleetFieldBoundedSchema,
    fleetFieldOptionsSchema,
    fleetFieldRegionSchema,
  ])
  .superRefine((constraint, ctx) => {
    if (constraint.kind === 'region' && !regionHasLocator(constraint)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Fleet field constraint region requires at least one locator.',
      })
    }
  })

const fleetPossiblyLostSchema = z.object({
  sinceTurn: z.number().int(),
  source: z.string(),
})

const fleetAlibiSchema = z.object({
  afterTurn: z.number().int(),
  sightingTurn: z.number().int(),
  source: z.string(),
})

export const fleetRowQualifiersSchema = z.object({
  possiblyLost: fleetPossiblyLostSchema.optional(),
  alibi: fleetAlibiSchema.optional(),
})

export const fleetBuildOptionSetSchema = z.object({
  comboId: z.string().optional(),
  label: z.string(),
  solutionRankWeight: z.number().int(),
  hullId: z.number().int().optional(),
  engineId: z.number().int().optional(),
  beamId: z.number().int().optional(),
  torpId: z.number().int().optional(),
  // null = unknown slot fill (fog); 0 = confirmed empty; >0 = fitted count.
  beamCount: z.number().int().nullable(),
  launcherCount: z.number().int().nullable(),
})

export const fleetLastSeenSchema = z.object({
  turn: z.number().int(),
  x: z.number().int(),
  y: z.number().int(),
  planetId: z.number().int().optional(),
})

export const fleetShipDispositionSchema = z.enum(['active', 'lost', 'traded', 'unknown'])

export type FleetFieldConstraint = z.infer<typeof fleetFieldConstraintSchema>
export type FleetRowQualifiers = z.infer<typeof fleetRowQualifiersSchema>
export type FleetBuildOptionSet = z.infer<typeof fleetBuildOptionSetSchema>
export type FleetLastSeen = z.infer<typeof fleetLastSeenSchema>
export type FleetShipDisposition = z.infer<typeof fleetShipDispositionSchema>
