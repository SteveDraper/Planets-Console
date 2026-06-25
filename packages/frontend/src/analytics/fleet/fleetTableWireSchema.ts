/**
 * Fleet table analytic wire: runtime validation and TypeScript types.
 * Default consumer filter: disposition === 'active' (see defaultActiveOnly on payload).
 */

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

export const fleetFieldConstraintSchema = z.discriminatedUnion('kind', [
  fleetFieldKnownSchema,
  fleetFieldUnknownSchema,
  fleetFieldBoundedSchema,
  fleetFieldOptionsSchema,
  fleetFieldRegionSchema,
])

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
  beamCount: z.number().int(),
  launcherCount: z.number().int(),
})

export const fleetLastSeenSchema = z.object({
  turn: z.number().int(),
  x: z.number().int(),
  y: z.number().int(),
  planetId: z.number().int().optional(),
})

const fleetShipDispositionSchema = z.enum(['active', 'lost', 'traded', 'unknown'])

const fleetShipRecordFieldsSchema = z.object({
  shipId: fleetFieldConstraintSchema,
  hull: fleetFieldConstraintSchema,
  engine: fleetFieldConstraintSchema,
  beams: fleetFieldConstraintSchema,
  launchers: fleetFieldConstraintSchema,
  builtTurn: fleetFieldConstraintSchema,
  location: fleetFieldConstraintSchema,
})

export const fleetTableRecordSchema = z
  .object({
    recordId: z.string(),
    disposition: fleetShipDispositionSchema,
    qualifiers: fleetRowQualifiersSchema,
    fields: fleetShipRecordFieldsSchema,
    buildOptionSets: z.array(fleetBuildOptionSetSchema),
    displayDefaultOptionSetIndex: z.number().int().min(0).optional(),
    lastSeen: fleetLastSeenSchema.optional(),
  })
  .strict()

export const fleetCountDiscrepancySchema = z.object({
  hostTurn: z.number().int(),
  activeRowCount: z.number().int(),
  scoreboardImpliedCount: z.number().int(),
  reportRefs: z.array(z.string()).optional(),
})

export const fleetTablePlayerSchema = z.object({
  playerId: z.number().int(),
  playerName: z.string(),
  discrepancy: fleetCountDiscrepancySchema.optional(),
  records: z.array(fleetTableRecordSchema),
})

export const fleetTableWireSchema = z.object({
  analyticId: z.literal('fleet'),
  defaultActiveOnly: z.literal(true),
  players: z.array(fleetTablePlayerSchema),
})

export type FleetFieldConstraint = z.infer<typeof fleetFieldConstraintSchema>
export type FleetRowQualifiers = z.infer<typeof fleetRowQualifiersSchema>
export type FleetBuildOptionSet = z.infer<typeof fleetBuildOptionSetSchema>
export type FleetLastSeen = z.infer<typeof fleetLastSeenSchema>
export type FleetTableRecord = z.infer<typeof fleetTableRecordSchema>
export type FleetCountDiscrepancy = z.infer<typeof fleetCountDiscrepancySchema>
export type FleetTablePlayer = z.infer<typeof fleetTablePlayerSchema>
export type FleetTableWire = z.infer<typeof fleetTableWireSchema>

/** Map stable validation failures to messages consumed by the SPA and tests. */
export function formatFleetTableWireValidationError(error: z.ZodError): string {
  const issue = error.issues[0]
  if (!issue) {
    return 'Fleet table payload has an invalid shape.'
  }

  if (issue.path[0] === 'analyticId') {
    return 'Fleet table payload analyticId must be fleet.'
  }

  if (issue.path[0] === 'defaultActiveOnly') {
    return 'Fleet table payload defaultActiveOnly must be true.'
  }

  if (issue.path.includes('disposition')) {
    return 'Fleet table record disposition is invalid.'
  }

  if (issue.path.includes('kind')) {
    return 'Fleet table field constraint kind is invalid.'
  }

  return 'Fleet table payload has an invalid shape.'
}
