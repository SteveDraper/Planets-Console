/**
 * Territory map wire: runtime validation and TypeScript types.
 * Core/BFF passthrough -- not central OpenAPI codegen.
 */

import { z } from 'zod'
import { MAP_REGION_FILL_PATTERNS } from '../../api/mapRegionOverlayTypes'

export const teamInformationTeamSchema = z.object({
  leagueTeamId: z.number().int().positive(),
  fillColor: z.string().min(1),
  fillPattern: z.enum(MAP_REGION_FILL_PATTERNS),
  playerIds: z.array(z.number().int()),
})

export const teamInformationPlayerSchema = z.object({
  playerId: z.number().int().positive(),
})

export const teamInformationPayloadSchema = z.object({
  analyticId: z.literal('team-information'),
  sphere: z.boolean(),
  teams: z.array(teamInformationTeamSchema),
  players: z.array(teamInformationPlayerSchema),
  /** Normalized via ``normalizeMapRegionOverlays`` after Zod accepts the array. */
  regionOverlays: z.array(z.unknown()),
})

export type TeamInformationTeam = z.infer<typeof teamInformationTeamSchema>
export type TeamInformationPlayer = z.infer<typeof teamInformationPlayerSchema>
export type TeamInformationPayload = z.infer<typeof teamInformationPayloadSchema>

export function parseTeamInformationPayload(raw: unknown): TeamInformationPayload | null {
  const result = teamInformationPayloadSchema.safeParse(raw)
  return result.success ? result.data : null
}
