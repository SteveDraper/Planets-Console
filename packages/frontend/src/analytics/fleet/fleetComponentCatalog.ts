import { z } from 'zod'

export const fleetComponentCatalogSchema = z.object({
  hulls: z.record(z.string(), z.string()),
  engines: z.record(z.string(), z.string()),
  beams: z.record(z.string(), z.string()),
  torpedoes: z.record(z.string(), z.string()),
})

export type FleetComponentCatalog = z.infer<typeof fleetComponentCatalogSchema>

export const EMPTY_FLEET_COMPONENT_CATALOG: FleetComponentCatalog = {
  hulls: {},
  engines: {},
  beams: {},
  torpedoes: {},
}

export function parseFleetComponentCatalog(raw: unknown): FleetComponentCatalog | null {
  const result = fleetComponentCatalogSchema.safeParse(raw)
  return result.success ? result.data : null
}

function catalogName(
  table: Record<string, string>,
  componentId: number | null | undefined
): string | null {
  if (componentId == null || componentId <= 0) {
    return null
  }
  return table[String(componentId)] ?? null
}

export function fleetHullName(catalog: FleetComponentCatalog, hullId: number): string | null {
  return catalogName(catalog.hulls, hullId)
}

export function fleetEngineName(catalog: FleetComponentCatalog, engineId: number): string | null {
  return catalogName(catalog.engines, engineId)
}

export function fleetBeamName(catalog: FleetComponentCatalog, beamId: number): string | null {
  return catalogName(catalog.beams, beamId)
}

export function fleetTorpedoName(catalog: FleetComponentCatalog, torpId: number): string | null {
  return catalogName(catalog.torpedoes, torpId)
}

export function formatComponentQuantityLabel(
  count: number,
  componentName: string | null,
  fallbackId: number | null = null
): string {
  if (count <= 0) {
    return '0'
  }
  if (componentName != null && componentName.length > 0) {
    return `${count} ${componentName}`
  }
  if (fallbackId != null && fallbackId > 0) {
    return `${count} (#${fallbackId})`
  }
  return String(count)
}
