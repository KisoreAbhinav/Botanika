import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The kiosk is served by FastAPI from one loopback origin; the build output is
// mounted at "/" by backend/src/botanika/api/app.py.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    // Development only: proxy API calls to the local FastAPI service.
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/media": "http://127.0.0.1:8000",
    },
  },
});
