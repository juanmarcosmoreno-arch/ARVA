/// <reference types="vitest" />
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.ARVA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: { "/api": apiTarget, "/health": apiTarget },
  },
  preview: {
    port: 4173,
    proxy: { "/api": apiTarget, "/health": apiTarget },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { echarts: ["echarts", "echarts-for-react"] } },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
