import {
  fleetTableWireSchema,
  formatFleetTableWireValidationError,
  type FleetTableWire,
} from './fleetTableWireSchema'

export type { FleetTableWire }

/** Parse a BFF fleet table response into a typed payload. */
export function parseFleetTableWire(payload: unknown): FleetTableWire {
  const result = fleetTableWireSchema.safeParse(payload)
  if (!result.success) {
    throw new Error(formatFleetTableWireValidationError(result.error))
  }
  return result.data
}
