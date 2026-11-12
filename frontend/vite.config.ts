import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The API is reached at /api on the app's own origin, in development (this proxy) and in
// production (a Vercel rewrite): the session cookie stays first-party and SameSite works.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: { '/api': { target: 'http://localhost:8010', changeOrigin: false } },
  },
});
