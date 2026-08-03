import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy live R2 data so local servers use real snapshots without CORS issues.
// Shared by `npm run dev` and `npm run preview` — preview serves the production
// build, so it needs the same routes to render anything.
const r2Proxy = {
  '/manifest.json': { target: 'https://labro.rossarnold.uk', changeOrigin: true },
  '/db': { target: 'https://labro.rossarnold.uk', changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // Pre-bundle sql.js so Vite's CJS→ESM wrapper gives a callable default export.
    // The WASM file is loaded at runtime via locateFile, so bundling the JS is fine.
    include: ['sql.js'],
  },
  server: { proxy: r2Proxy },
  preview: { proxy: r2Proxy },
});
