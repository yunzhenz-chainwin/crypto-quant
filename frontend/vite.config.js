import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 所有 /api 開頭的請求都轉發到 FastAPI
      '/api': 'http://localhost:8000',
    },
  },
})
