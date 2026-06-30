import {
  fleetTableStreamEventSchema,
  formatFleetTableStreamValidationError,
  type FleetTableStreamEvent,
} from './fleetTableStreamEventSchema'

export type { FleetTableStreamEvent }

export function parseFleetTableStreamEvent(line: string): FleetTableStreamEvent | null {
  const trimmed = line.trim()
  if (!trimmed) {
    return null
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error('Fleet table stream returned invalid JSON.')
  }
  const result = fleetTableStreamEventSchema.safeParse(parsed)
  if (!result.success) {
    throw new Error(formatFleetTableStreamValidationError(result.error))
  }
  return result.data
}
