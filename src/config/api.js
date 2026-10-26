// Centralized API base URL.
//
// - Web dev (`npm run dev`) defaults to the local FastAPI backend on 127.0.0.1.
// - For the Capacitor Android build, set VITE_API_BASE_URL at build time to a URL
//   the device can actually reach (127.0.0.1 refers to the device itself, not
//   your dev machine, so it will NOT work on a phone/emulator):
//     • Android emulator → http://10.0.2.2:8001   (10.0.2.2 maps to host loopback)
//     • Physical device  → http://<your-LAN-IP>:8001   e.g. http://192.168.1.10:8001
//     • Production       → https://api.yourdomain.com
//
// Build example:
//   $env:VITE_API_BASE_URL="http://10.0.2.2:8001"; npm run build
// Port note: 8000 is frequently occupied on Windows; 8001 is the project default.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8001";
