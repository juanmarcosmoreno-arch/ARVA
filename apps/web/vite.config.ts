/// <reference types="vitest" />
import { readFileSync } from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const { version } = JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf8")) as { version: string };
const apiTarget = process.env.ARVA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  define: { __ARVA_VERSION__: JSON.stringify(version) },
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
