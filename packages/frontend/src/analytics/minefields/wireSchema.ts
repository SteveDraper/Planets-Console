/**
 * Minefields map wire: runtime validation and TypeScript types.
 * Core/BFF passthrough facts -- not central OpenAPI codegen.
 */

import { z } from 'zod'

export const knownMinefieldSchema = z.object({
  id: z.number().int(),
  ownerId: z.number().int(),
  isWeb: z.boolean(),
  isHidden: z.boolean(),
  x: z.number(),
  y: z.number(),
  units: z.number().int(),
  infoTurn: z.number().int(),
  friendlyCode: z.string(),
  preRadius: z.number().int().nonnegative(),
  postRadius: z.number().int().nonnegative(),
})

export type KnownMinefield = z.infer<typeof knownMinefieldSchema>

export function parseKnownMinefield(raw: unknown): KnownMinefield | null {
  const result = knownMinefieldSchema.safeParse(raw)
  return result.success ? result.data : null
}

export function parseKnownMinefields(raw: unknown): KnownMinefield[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map(parseKnownMinefield)
    .filter((field): field is KnownMinefield => field != null)
}
