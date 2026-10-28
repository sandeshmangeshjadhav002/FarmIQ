import type { CapacitorConfig } from "@capacitor/cli";

// Set CAPACITOR_DEV_HTTP=1 when running `cap sync` for a local-HTTP backend
// (emulator / LAN device). Release syncs leave it unset, so mixed content stays
// blocked and the app can only call the HTTPS production API.
const allowDevHttp = process.env.CAPACITOR_DEV_HTTP === "1";

const config: CapacitorConfig = {
  appId: "com.farmiq.app",
  appName: "FarmIQ",
  webDir: "dist",
  android: {
    // The WebView origin is https://localhost (Capacitor default scheme); an
    // http:// dev backend is mixed content, allowed only for dev syncs.
    // Android cleartext is additionally restricted to debug builds
    // (android/app/src/debug/res/xml/network_security_config.xml).
    allowMixedContent: allowDevHttp,
  },
};

export default config;
