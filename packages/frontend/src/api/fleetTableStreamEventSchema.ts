/**
 * Fleet table NDJSON stream: runtime validation and TypeScript types.
 */

import { z } from 'zod'
import {
  fleetTablePlayerSchema,
  fleetTableRecordSchema,
} from '../analytics/fleet/fleetTableWireSchema'

const fleetTableStreamPlayerScopeSchema = z.object({
  playerId: z.number().int().optional(),
})

export const fleetTableStreamLedgerUpdatedEventSchema =
  fleetTableStreamPlayerScopeSchema.extend({
    type: z.literal('ledger_updated'),
    ledger: fleetTablePlayerSchema,
  })

export const fleetTableStreamRecordRefinedEventSchema =
  fleetTableStreamPlayerScopeSchema.extend({
    type: z.literal('record_refined'),
    record: fleetTableRecordSchema,
  })

export const fleetTableStreamProvenanceEventSchema =
  fleetTableStreamPlayerScopeSchema.extend({
    type: z.literal('provenance'),
    turnEvidenceAtN: z.boolean(),
    priorLedgerAtNMinus1: z.boolean(),
    isFinal: z.boolean(),
  })

export const fleetTableStreamCompleteEventSchema = fleetTableStreamPlayerScopeSchema.extend({
  type: z.literal('complete'),
  isFinal: z.boolean(),
  summary: z.string(),
})

export const fleetTableStreamErrorEventSchema = fleetTableStreamPlayerScopeSchema.extend({
  type: z.literal('error'),
  detail: z.string(),
})

export const fleetTableStreamEventSchema = z.discriminatedUnion('type', [
  fleetTableStreamLedgerUpdatedEventSchema,
  fleetTableStreamRecordRefinedEventSchema,
  fleetTableStreamProvenanceEventSchema,
  fleetTableStreamCompleteEventSchema,
  fleetTableStreamErrorEventSchema,
])

export type FleetTableStreamEvent = z.infer<typeof fleetTableStreamEventSchema>

export function formatFleetTableStreamValidationError(error: z.ZodError): string {
  const issue = error.issues[0]
  if (!issue) {
    return 'Fleet table stream event has an invalid shape.'
  }
  if (issue.code === 'invalid_union_discriminator') {
    return 'Fleet table stream returned unknown event type.'
  }
  if (issue.path.includes('detail')) {
    return 'Fleet table stream error event has an invalid shape.'
  }
  return 'Fleet table stream event has an invalid shape.'
}
