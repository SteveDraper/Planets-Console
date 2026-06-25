/**
 * Fleet table analytic wire: runtime validation and TypeScript types.
 * Default consumer filter: disposition === 'active' (see defaultActiveOnly on payload).
 */

import { z } from 'zod'
import {
  fleetBuildOptionSetSchema,
  fleetFieldConstraintSchema,
  fleetLastSeenSchema,
  fleetRowQualifiersSchema,
  fleetShipDispositionSchema,
} from './fleetWirePrimitives'

export {
  fleetBuildOptionSetSchema,
  fleetFieldConstraintSchema,
  fleetLastSeenSchema,
  fleetRowQualifiersSchema,
  fleetShipDispositionSchema,
} from './fleetWirePrimitives'
export type {
  FleetBuildOptionSet,
  FleetFieldConstraint,
  FleetLastSeen,
  FleetRowQualifiers,
  FleetShipDisposition,
} from './fleetWirePrimitives'

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

export const fleetTablePlayerSchema = z
  .object({
    playerId: z.number().int(),
    playerName: z.string(),
    discrepancy: fleetCountDiscrepancySchema.optional(),
    records: z.array(fleetTableRecordSchema),
  })
  .strict()

export const fleetTableWireSchema = z
  .object({
    analyticId: z.literal('fleet'),
    defaultActiveOnly: z.literal(true),
    players: z.array(fleetTablePlayerSchema),
  })
  .strict()

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
