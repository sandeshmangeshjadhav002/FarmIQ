import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.farmiq.app",
  appName: "FarmIQ",
  webDir: "dist",
  android: {
    // The app shell is served over the default https scheme. The FastAPI dev
    // backend is HTTP, so we allow mixed content to let the WebView reach it
    // during development. Cleartext traffic is also gated by Android's network
    // security config (see android/app/src/main/res/xml/network_security_config.xml).
    allowMixedContent: true,
  },
};

export default config;
