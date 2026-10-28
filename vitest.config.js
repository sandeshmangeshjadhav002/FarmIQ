import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Dedicated test config, kept separate from vite.config.js so the Tailwind and
// React (react-refresh) plugins — only needed for builds and dev — are not run
// during unit tests. `@vitejs/plugin-react` v6 drives Vite 8's oxc-based JSX
// transform, which the Vite version bundled with Vitest does not have, so the
// automatic JSX runtime is configured directly through esbuild here.
export default defineConfig({
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
  },
});
