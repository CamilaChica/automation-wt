import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const repositoryName = process.env.GITHUB_REPOSITORY?.split('/')[1];
const computedPagesBase = repositoryName ? `/${repositoryName}/` : '/';
const basePath = process.env.VITE_BASE_PATH || (process.env.GITHUB_PAGES === 'true' ? computedPagesBase : '/');

export default defineConfig({
  base: basePath,
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
