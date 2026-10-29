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
  plugins: {
    StatusBar: {
      // Dark icons (clock, battery, wifi drawn in dark/black).
      // FarmIQ has a light background (#E9EFEA); light (white) icons would
      // be invisible — this is the root cause of the "mixed" appearance.
      // Mirrors the android:windowLightStatusBar theme attribute so the
      // setting is already correct before JS executes (no icon-colour flash).
      style: "DARK",

      // The WebView draws behind the transparent status bar (edge-to-edge).
      // On Android 15+ (targetSdkVersion ≥ 35) this is OS-enforced regardless.
      // On older devices this keeps the layout consistent.
      // CSS env(safe-area-inset-top) in index.css then offsets the content.
      overlaysWebView: true,
    },
  },
};

export default config;
