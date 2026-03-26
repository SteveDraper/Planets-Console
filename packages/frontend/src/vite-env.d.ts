/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Optional short git SHA for display, e.g. set in CI: `VITE_GIT_COMMIT_SHORT=$(git rev-parse --short HEAD) vite build`.
   * Prefer injecting at build time over committing a generated file that needs updating every merge.
   */
  readonly VITE_GIT_COMMIT_SHORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
