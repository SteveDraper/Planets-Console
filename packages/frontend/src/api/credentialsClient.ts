import { bffRequest } from './bff'
import { throwBffHttpErrorFromResponse } from './bffHttpError'

/** Credential probe: decryptable account API key present for username (no Planets.nu call). */
export async function probeCredentials(username: string): Promise<boolean> {
  const trimmed = username.trim()
  const path = `/bff/credentials/probe?username=${encodeURIComponent(trimmed)}`
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
  const body = (await r.json()) as { present?: boolean }
  return body.present === true
}

/** Login exchange: Planets.nu login + store obfuscated account API key. */
export async function exchangeCredentials(username: string, password: string): Promise<void> {
  const path = '/bff/credentials/exchange'
  const endpointLabel = `POST ${path}`
  const r = await bffRequest(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.trim(), password }),
    },
    endpointLabel
  )
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
}

/** Account API key drop for a login name. */
export async function dropCredentials(username: string): Promise<void> {
  const trimmed = username.trim()
  const path = `/bff/credentials/${encodeURIComponent(trimmed)}`
  const endpointLabel = `DELETE ${path}`
  const r = await bffRequest(path, { method: 'DELETE' }, endpointLabel)
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
}
