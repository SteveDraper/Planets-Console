import appVersion from '../assets/appVersion.json'

function trimmedGitCommitShortFromEnv(): string | null {
  const raw = import.meta.env.VITE_GIT_COMMIT_SHORT
  if (typeof raw !== 'string') {
    return null
  }
  const trimmed = raw.trim()
  return trimmed.length > 0 ? trimmed : null
}

/**
 * Human-readable version for the About dialog. Release version comes from `appVersion.json`.
 * An optional git short SHA is appended when `VITE_GIT_COMMIT_SHORT` is set at build time (e.g. in
 * GitHub Actions before `vite build`). Committing a file that stores the SHA and updating it on
 * every merge would work but adds noise commits; build-time env injection avoids that.
 */
export function getAppVersionDisplayString(): string {
  const base = appVersion.version
  const sha = trimmedGitCommitShortFromEnv()
  return sha != null ? `${base} (${sha})` : base
}
