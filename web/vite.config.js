import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(() => {
  const backendTarget = process.env.VITE_PPT_BACKEND_PROXY ?? 'http://localhost:8000'
  return {
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    globals: true,
    css: true,
    include: ['tests/**/*.spec.ts', 'src/**/*.spec.ts'],
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api/v1/docs-pipeline': {
        target: process.env.VITE_DOCS_BACKEND_PROXY ?? 'http://localhost:8003',
        changeOrigin: true,
      },
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
}})
