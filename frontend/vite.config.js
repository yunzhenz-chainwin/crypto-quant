import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: {
      // 所有 /api 開頭的請求都轉發到 FastAPI
      '/api': 'http://localhost:8001',
    },
  },
})
