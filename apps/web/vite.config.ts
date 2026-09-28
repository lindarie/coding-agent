import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, forward /api to the FastAPI process (pnpm dev:agent).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.AGENT_URL ?? "http://localhost:8000", changeOrigin: true } },
  },
});
