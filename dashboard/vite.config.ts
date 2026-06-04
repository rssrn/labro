import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // sql.js ships a pre-built UMD bundle; exclude it from Vite's dep optimisation
    // so the WASM sibling file is picked up correctly at runtime.
    exclude: ['sql.js'],
  },
});
