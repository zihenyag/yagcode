import { defineConfig } from "vitest/config";

export default defineConfig({
  build: {
    rollupOptions: {
      input: "src/renderer/index.html",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/renderer/__tests__/setup.ts"],
  },
});
