import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  // tsconfig.json sets `jsx: "preserve"` because Next handles the transform in
  // the app build. esbuild honours that here too and emits React.createElement
  // without an import, so tests fail with "React is not defined". Pin the
  // automatic runtime for the test transform only.
  esbuild: { jsx: "automatic" },
});
