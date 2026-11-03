import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // e2e/ holds Playwright scripts (website screenshots), not unit tests.
  test: {
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
  server: {
    host: "0.0.0.0",
    port: 5179,
    // Required so file changes are picked up inside the Docker container.
    watch: {
      usePolling: true,
    },
  },
});
