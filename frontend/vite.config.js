import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {
      '/api': process.env.VITE_REVIEW_API_TARGET || 'http://127.0.0.1:18180',
    },
  },
  preview: {
    port: 4174,
    strictPort: true,
    proxy: { '/api': process.env.VITE_REVIEW_API_TARGET || 'http://127.0.0.1:18180' },
  },
})
