import { useState, useCallback, useEffect } from "react";

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

import HomeScreen from "@/pages/HomeScreen";
import ChatScreen from "@/pages/ChatScreen";
import FarmScreen from "@/pages/FarmScreen";
import AdviceScreen from "@/pages/AdviceScreen";
import HistoryScreen from "@/pages/HistoryScreen";
import LoginScreen from "@/pages/LoginScreen";
import RegisterScreen from "@/pages/RegisterScreen";

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
    return <LoginScreen navigate={navigate} onLogin={handleLogin} />;
  }
  if (screen === "register") {
    return <RegisterScreen navigate={navigate} onLogin={handleLogin} />;
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
