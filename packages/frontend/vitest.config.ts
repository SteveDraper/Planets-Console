import { defineConfig } from 'vitest/config'
import { mergeConfig } from 'vite'
import viteConfig from './vite.config.ts'

// `test` is typed on Vitest's config, not Vite's — merge keeps vite.config.ts free of suppressions.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      // One worker avoids many vitest/node processes at 100% CPU on this small suite; raise if tests get slow.
      maxWorkers: 1,
      fileParallelism: false,
    },
  })
)
