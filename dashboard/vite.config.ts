import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // Pre-bundle sql.js so Vite's CJS→ESM wrapper gives a callable default export.
    // The WASM file is loaded at runtime via locateFile, so bundling the JS is fine.
    include: ['sql.js'],
  },
  server: {
    // Proxy live R2 data in dev so `npm run dev` uses real snapshots without CORS issues.
    proxy: {
      '/manifest.json': { target: 'https://labro.rossarnold.uk', changeOrigin: true },
      '/db': { target: 'https://labro.rossarnold.uk', changeOrigin: true },
    },
  },
});
