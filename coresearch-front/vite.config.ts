import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api/ws': {
        target: `ws://${process.env.API_HOST ?? 'localhost:8000'}`,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      '/api': {
        target: `http://${process.env.API_HOST ?? 'localhost:8000'}`,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
