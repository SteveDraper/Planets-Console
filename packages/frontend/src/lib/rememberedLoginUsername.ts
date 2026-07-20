/** Last successful login name only (never the password). */
export const LAST_LOGIN_USERNAME_STORAGE_KEY = 'planetsConsoleLastLoginUsername'

export function readRememberedLoginUsername(): string {
  try {
    return localStorage.getItem(LAST_LOGIN_USERNAME_STORAGE_KEY)?.trim() ?? ''
  } catch {
    return ''
  }
}

export function writeRememberedLoginUsername(username: string): void {
  try {
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, username)
  } catch {
    // ignore quota / private mode
  }
}

export function clearRememberedLoginUsername(): void {
  try {
    localStorage.removeItem(LAST_LOGIN_USERNAME_STORAGE_KEY)
  } catch {
    // ignore
  }
}
