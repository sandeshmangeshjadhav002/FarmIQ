// Centralized API base URL — the ONLY place the backend address is decided.
//
// Resolved from VITE_API_BASE_URL, which Vite loads per build *mode*:
//   npm run dev              -> .env / .env.local        (browser; falls back to 127.0.0.1:8001)
//   npm run build:emulator   -> .env.emulator            (http://10.0.2.2:8001)
//   npm run build:device     -> .env.device.local        (your LAN IP; gitignored)
//   npm run build            -> .env.production(.local)  (https://<deployed API>)
//
// Inside the Android WebView `localhost` / 127.0.0.1 is the phone itself, never
// your computer, so the 127.0.0.1 fallback is allowed in `npm run dev` only.
const rawUrl = import.meta.env.VITE_API_BASE_URL;
const isNative =
  typeof window !== "undefined" && !!window.Capacitor?.isNativePlatform?.();

function resolveBaseUrl() {
  if (rawUrl) return String(rawUrl).trim().replace(/\/+$/, "");
  if (import.meta.env.DEV) return "http://127.0.0.1:8001";
  console.error(
    "[FarmIQ] VITE_API_BASE_URL is not set for this build; API calls will fail. " +
      "See 'Backend connectivity' in readme.md.",
  );
  return "";
}

export const API_BASE_URL = resolveBaseUrl();

if (isNative && /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(API_BASE_URL)) {
  console.error(
    `[FarmIQ] API_BASE_URL (${API_BASE_URL}) points at the device itself. ` +
      "Use 10.0.2.2 (emulator), your LAN IP (device) or the HTTPS production URL.",
  );
}

if (
  import.meta.env.MODE === "production" &&
  API_BASE_URL &&
  !API_BASE_URL.startsWith("https://")
) {
  console.error("[FarmIQ] Production build uses a non-HTTPS API URL:", API_BASE_URL);
}
