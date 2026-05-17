import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror tsconfig.json paths so '@/' resolves at build time (tsconfig paths를 빌드 시 반영)
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,                  // bind 0.0.0.0 so phones/tablets on same Wi-Fi can connect
    allowedHosts: true,
    proxy: {
      // Proxy API calls to FastAPI backend (FastAPI 백엔드로 API 호출 프록시)
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
