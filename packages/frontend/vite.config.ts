import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// Vitest options live in `vitest.config.ts` (merged) so this file stays valid Vite-only config for `tsc` + the Vite CLI.
export default defineConfig({
  plugins: [react()],
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
