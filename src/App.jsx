import { Suspense, useState, useCallback, useEffect, lazy } from "react";

import {
  setAuthToken,
  clearAuthToken,
  saveUser,
  loadUser,
  getAuthToken,
} from "@/lib/apiClient";

import DesktopNavigation from "@/components/layout/DesktopNavigation";
import LanguageSheet from "@/components/layout/LanguageSheet";
import ScreenShell from "@/components/layout/ScreenShell";
import ProfilePanel from "@/components/layout/ProfilePanel";
import ScreenLoader from "@/components/common/ScreenLoader";
import ModuleHub from "@/components/modules/ModuleHub";
import ModuleScreen from "@/components/modules/ModuleScreen";

// Detect if running inside Capacitor (Android / iOS native app).
// When running as a native app we skip the desktop sidebar entirely.
const IS_NATIVE =
  typeof window !== "undefined" &&
  (window.Capacitor?.isNativePlatform?.() ?? false);

// Screen hierarchy for hardware back button navigation
const BACK_MAP = {
  home: null, // top — exits app
  chat: "home",
  farm: "home",
  advice: "home",
  history: "home",
  more: "home",
  module: "more",
};

// Screens are split into their own chunks: only the screen the farmer opens is
// downloaded, so the first paint no longer waits for every page (and, through
// ModuleScreen, every module panel). Each is wrapped in a Suspense boundary at
// the point of use.
const HomeScreen = lazy(() => import("@/pages/HomeScreen"));
const ChatScreen = lazy(() => import("@/pages/ChatScreen"));
const FarmScreen = lazy(() => import("@/pages/FarmScreen"));
const AdviceScreen = lazy(() => import("@/pages/AdviceScreen"));
const HistoryScreen = lazy(() => import("@/pages/HistoryScreen"));
const LoginScreen = lazy(() => import("@/pages/LoginScreen"));
const RegisterScreen = lazy(() => import("@/pages/RegisterScreen"));

/**
 * Root application component.
 *
 * Manages top-level navigation state and renders the correct screen.
 * The desktop sidebar is shown at lg+ breakpoints alongside the mobile shell.
 *
 * Callbacks are memoized with useCallback to avoid triggering unnecessary
 * re-renders in child components that receive them as props.
 */
export default function App() {
  // Restore session from localStorage on app start (survives Android restart)
  const [user, setUser] = useState(() => loadUser());
  const [screen, setScreen] = useState(() => {
    const saved = loadUser();
    return saved && getAuthToken() ? "home" : "login";
  });
  const [language, setLanguage] = useState("English");
  const [languageOpen, setLanguageOpen] = useState(false);
  const [selectedModule, setSelectedModule] = useState("crop-recommendation");

  const [profileOpen, setProfileOpen] = useState(false);

  const navigate = useCallback((next) => {
    setScreen(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openModule = useCallback((module) => {
    setSelectedModule(module);
    setScreen("module");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openLanguages = useCallback(() => setLanguageOpen(true), []);

  const handleLanguageSelect = useCallback((next) => {
    setLanguage(next);
    setLanguageOpen(false);
  }, []);

  /** Called by LoginScreen / RegisterScreen once auth succeeds. */
  const handleLogin = useCallback(
    (userData) => {
      // Capture the Supabase access token for protected backend requests.
      setAuthToken(userData?.access_token);
      saveUser(userData);
      setUser(userData);
      navigate("home");
    },
    [navigate],
  );

  /** Log out — clear user data and return to login. */
  const handleLogout = useCallback(() => {
    clearAuthToken(); // also clears localStorage token + user
    setProfileOpen(false);
    setUser(null);
    setScreen("login");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  // ── Android status bar ───────────────────────────────────────────────────
  // Configure icon colour and overlay mode once on mount. The theme attribute
  // android:windowLightStatusBar already sets dark icons at the native layer,
  // but calling the plugin here keeps the setting correct after orientation
  // changes or any Capacitor lifecycle event that might reset the window flags.
  useEffect(() => {
    if (!IS_NATIVE) return;
    (async () => {
      try {
        const { StatusBar, Style } = await import("@capacitor/status-bar");
        // Dark icons (clock, battery, wifi are drawn dark/black).
        // FarmIQ has a light background (#E9EFEA) — white icons disappear.
        await StatusBar.setStyle({ style: Style.Dark });
        // Keep the WebView drawing behind the transparent status bar.
        // On Android 15+ (targetSdkVersion ≥ 35) this is OS-enforced;
        // on older devices it ensures the same edge-to-edge layout so that
        // the CSS env(safe-area-inset-top) compensation in index.css works.
        await StatusBar.setOverlaysWebView({ overlay: true });
      } catch {
        // @capacitor/status-bar unavailable in the web/desktop context — ignore.
      }
    })();
  }, []); // Run once on mount; theme attr covers the launch-screen window flags.

  // ── Android hardware back button ──────────────────────────────────────────
  useEffect(() => {
    if (!IS_NATIVE) return;
    let listener;
    (async () => {
      try {
        const { App: CapApp } = await import("@capacitor/app");
        listener = await CapApp.addListener("backButton", ({ canGoBack }) => {
          if (profileOpen) {
            setProfileOpen(false);
            return;
          }
          if (languageOpen) {
            setLanguageOpen(false);
            return;
          }
          const prev = BACK_MAP[screen];
          if (prev) {
            setScreen(prev);
            window.scrollTo({ top: 0, behavior: "smooth" });
          } else {
            // On home screen — minimize app (standard Android behaviour)
            CapApp.minimizeApp?.();
          }
        });
      } catch {
        // @capacitor/app not available in web preview — ignore silently
      }
    })();
    return () => {
      listener?.remove?.();
    };
  }, [screen, profileOpen, languageOpen]);

  // ── Auth screens (no desktop nav / bottom nav) ────────────────────────────
  if (screen === "login") {
    return (
      <Suspense fallback={<ScreenLoader label="Loading sign-in…" />}>
        <LoginScreen navigate={navigate} onLogin={handleLogin} />
      </Suspense>
    );
  }
  if (screen === "register") {
    return (
      <Suspense fallback={<ScreenLoader label="Loading sign-up…" />}>
        <RegisterScreen navigate={navigate} onLogin={handleLogin} />
      </Suspense>
    );
  }

  // ── Main app ──────────────────────────────────────────────────────────────
  return (
    <div
      className={`relative min-h-dvh bg-[#E9EFEA] bg-[url('/app-bg.jpg')] bg-cover bg-center bg-fixed ${
        IS_NATIVE
          ? ""
          : "lg:flex lg:items-start lg:justify-center lg:gap-5 lg:px-6 lg:py-6"
      }`}
    >
      {/* Sidebar only shown on desktop browser — never on native Android/iOS */}
      {!IS_NATIVE && (
        <DesktopNavigation
          activeModule={screen === "module" ? selectedModule : undefined}
          onAssistant={() => navigate("chat")}
          onHome={() => navigate("home")}
          onOpen={openModule}
        />
      )}

      {/* Content — full width on native, capped on desktop */}
      <div className={`w-full ${IS_NATIVE ? "" : "lg:max-w-[430px]"} relative`}>
        {/* Only the active screen is inside the boundary, so the sidebar and
            content column stay painted while a chunk is being fetched. */}
        <Suspense fallback={<ScreenLoader />}>
          {screen === "home" && (
            <HomeScreen
              language={language}
              navigate={navigate}
              openLanguages={openLanguages}
              openTools={() => navigate("more")}
              openModule={openModule}
              user={user}
              onOpenProfile={() => setProfileOpen(true)}
            />
          )}
          {screen === "chat" && (
            <ChatScreen
              language={language}
              navigate={navigate}
              openLanguages={openLanguages}
              openModule={openModule}
            />
          )}
          {screen === "farm" && <FarmScreen navigate={navigate} />}
          {screen === "advice" && <AdviceScreen navigate={navigate} />}
          {screen === "history" && <HistoryScreen navigate={navigate} />}
          {screen === "more" && (
            <ScreenShell active="home" navigate={navigate}>
              <ModuleHub onBack={() => navigate("home")} onOpen={openModule} />
            </ScreenShell>
          )}
          {screen === "module" && (
            <ScreenShell active="home" navigate={navigate}>
              <ModuleScreen
                currentLanguage={language}
                moduleKey={selectedModule}
                onAsk={() => navigate("chat")}
                onBack={() => navigate("more")}
                onLanguage={setLanguage}
              />
            </ScreenShell>
          )}
        </Suspense>

        {/* Language sheet — scoped inside the content column */}
        {languageOpen && (
          <div className="absolute inset-0 z-50">
            <LanguageSheet
              onClose={() => setLanguageOpen(false)}
              onSelect={handleLanguageSelect}
              selected={language}
            />
          </div>
        )}

        {/* Profile panel — scoped inside the content column */}
        {profileOpen && (
          <ProfilePanel
            user={user}
            onClose={() => setProfileOpen(false)}
            onLogout={handleLogout}
            onUpdate={(updated) => setUser(updated)}
          />
        )}
      </div>
    </div>
  );
}
