/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API_TARGET = process.env.FINBOARD_API_URL ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Same origin for the browser: no CORS anywhere (ADR-0015). changeOrigin stays false so the
    // backend sees Host = the page's host, which matches the browser's Origin header.
    proxy: { '/api': { target: API_TARGET, changeOrigin: false } },
  },
  build: {
    // `finboard serve` serves the SPA from the backend package (single-port mode).
    outDir: '../backend/src/finboard/web/static',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
})
