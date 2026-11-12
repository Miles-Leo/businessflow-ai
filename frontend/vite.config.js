import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ command, mode, isPreview }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const proxy = Object.fromEntries(['/api', '/health', '/docs', '/openapi.json', '/redoc'].map(path => [path, { target }]))
  return {
    plugins: [vue()],
    base: command === 'build' || isPreview ? '/app/' : '/',
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, strictPort: true, proxy },
    build: { outDir: 'dist' },
  }
})
