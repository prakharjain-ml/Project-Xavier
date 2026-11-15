import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go to dist/, which interface/web/server.py serves (and Vercel hosts as a static site).
// The dev server proxies the backend so `npm run dev` behaves like the served build.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/video": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
