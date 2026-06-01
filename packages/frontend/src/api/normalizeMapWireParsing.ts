/** Shared syntactic parsers for BFF map wire JSON. */

/** Parse a single JSON number; rejects null, non-numeric, and `Number('')` → 0. */
export function parseJsonFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null
  }
  if (typeof value === 'string') {
    if (value.trim() === '') return null
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** Parse a map grid cell index; must be a finite integer (no boolean/null/`""` coercion). */
export function parseJsonInteger(value: unknown): number | null {
  const n = parseJsonFiniteNumber(value)
  if (n == null || !Number.isInteger(n)) return null
  return n
}

/**
 * 2D offset tuple from the wire. Each element must be a finite `number` or a non-empty
 * numeric string — never `Number()` on arbitrary values (avoids `null`/`""` → `0`).
 */
export function parseFiniteNumberPair(
  s: Record<string, unknown>,
  camelKey: string,
  snakeKey: string
): [number, number] | undefined {
  const raw = s[camelKey] ?? s[snakeKey]
  if (raw == null) return undefined
  if (!Array.isArray(raw) || raw.length !== 2) return undefined
  const a = parseJsonFiniteNumber(raw[0])
  const b = parseJsonFiniteNumber(raw[1])
  if (a == null || b == null) return undefined
  return [a, b]
}
