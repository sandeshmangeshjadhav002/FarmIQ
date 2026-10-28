import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // Relative base so bundled assets resolve correctly inside the Capacitor
  // Android WebView (which loads the app from a file:// / local origin).
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        // React and its scheduler are the only vendor code that is always
        // needed, so they get a stable long-lived chunk: app releases then
        // invalidate just the app code. Everything else (the Capacitor voice
        // plugins, for example) stays with the lazy chunk that actually uses
        // it instead of being hoisted into the entry bundle.
        manualChunks(id) {
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) {
            return "react-vendor";
          }
          return undefined;
        },
      },
    },
  },
});
