/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Vitest adds `test`; Vite's `UserConfig` type does not include it (see reference types above).
  // @ts-expect-error TS2769: vitest extends ViteConfig with `test`
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // One worker avoids many vitest/node processes at 100% CPU on this small suite; raise if tests get slow.
    maxWorkers: 1,
    fileParallelism: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/bff': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // Same MRU buffer as /bff/diagnostics/recent (root app); used when /bff is not routed
      '/diagnostics': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
