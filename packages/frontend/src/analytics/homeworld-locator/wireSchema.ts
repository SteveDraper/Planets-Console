/**
 * Homeworld locator map/table wire: runtime validation and TypeScript types.
 * Core/BFF passthrough shape from ``homeworld_locator.compute._view_to_wire``.
 */

import { z } from 'zod'
import { CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE } from './constants'

export const homeworldConfidenceTierSchema = z.enum([
  CONFIDENCE_DEFINITE,
  CONFIDENCE_POSSIBLE,
])

export const homeworldCandidateRecordSchema = z.object({
  planetId: z.number().int(),
  perspective: z.number().int().nullable(),
  confidenceTier: homeworldConfidenceTierSchema,
  attribution: z.string().min(1),
  /** Derived cue: asserted-strength provenance present on location and/or ownership. */
  assertedCue: z.boolean().default(false),
  /** Derived: asserted-strength provenance present on the location axis only. */
  locationAsserted: z.boolean().default(false),
  isMostProbable: z.boolean().default(false),
})

export const homeworldMapMarkerSchema = homeworldCandidateRecordSchema

export const homeworldLocatorPayloadSchema = z.object({
  analyticId: z.string(),
  available: z.boolean(),
  inactiveReason: z.string().nullable().optional(),
  baselineDegraded: z.boolean(),
  baselineTurn: z.number().int().positive().nullable().optional(),
  markers: z.array(homeworldMapMarkerSchema).optional(),
  rows: z.array(homeworldCandidateRecordSchema).optional(),
  nodes: z.array(z.unknown()).optional(),
  edges: z.array(z.unknown()).optional(),
  /** Normalized via ``normalizeMapRegionOverlays`` after Zod accepts the array. */
  regionOverlays: z.array(z.unknown()).optional(),
})

export type HomeworldConfidenceTier = z.infer<typeof homeworldConfidenceTierSchema>
export type HomeworldCandidateRecord = z.infer<typeof homeworldCandidateRecordSchema>
export type HomeworldMapMarker = z.infer<typeof homeworldMapMarkerSchema>
export type HomeworldLocatorPayload = z.infer<typeof homeworldLocatorPayloadSchema>

export function parseHomeworldLocatorPayload(raw: unknown): HomeworldLocatorPayload | null {
  const result = homeworldLocatorPayloadSchema.safeParse(raw)
  return result.success ? result.data : null
}
