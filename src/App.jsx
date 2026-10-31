import { Suspense, useState, useCallback, useEffect, lazy } from "react";
import { useTranslation } from "react-i18next";

import {
  setAuthToken,
  clearAuthToken,
  saveUser,
  loadUser,
  getAuthToken,
} from "@/lib/apiClient";
import { LocationProvider } from "@/lib/locationStore";
import { normalizeLanguage } from "@/i18n/language";
import useLanguage from "@/i18n/useLanguage";

import DesktopNavigation from "@/components/layout/DesktopNavigation";
import LanguageSheet from "@/components/layout/LanguageSheet";
import ScreenShell from "@/components/layout/ScreenShell";
import ProfilePanel from "@/components/layout/ProfilePanel";
import ScreenLoader from "@/components/common/ScreenLoader";
import ModuleHub from "@/components/modules/ModuleHub";
import ModuleScreen from "@/components/modules/ModuleScreen";
import { moduleByKey, navKeyForSection } from "@/data/modules";

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
  advisor: "home",
  insights: "home",
  history: "home",
  more: "home",
  module: "more", // overridden by the module's own return screen (see below)
};

// Screens are split into their own chunks: only the screen the farmer opens is
// downloaded, so the first paint no longer waits for every page (and, through
// ModuleScreen, every module panel). Each is wrapped in a Suspense boundary at
// the point of use.
const HomeScreen = lazy(() => import("@/pages/HomeScreen"));
const ChatScreen = lazy(() => import("@/pages/ChatScreen"));
const FarmScreen = lazy(() => import("@/pages/FarmScreen"));
const AdvisorScreen = lazy(() => import("@/pages/AdvisorScreen"));
const InsightsScreen = lazy(() => import("@/pages/InsightsScreen"));
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
  const { t } = useTranslation();
  // Restore session from localStorage on app start (survives Android restart)
  const [user, setUser] = useState(() => loadUser());
  const [screen, setScreen] = useState(() => {
    const saved = loadUser();
    return saved && getAuthToken() ? "home" : "login";
  });
  // The selected language is held by i18next (see src/i18n). ``language`` is the
  // "en" | "mr" code; ``changeLanguage`` persists it for guests (localStorage)
  // and mirrors it into the signed-in user's Supabase profile.
  const { language, changeLanguage } = useLanguage();
  const [languageOpen, setLanguageOpen] = useState(false);
  const [selectedModule, setSelectedModule] = useState("crop-recommendation");
  // Where the hardware/UI back button returns to from an open module. Modules
  // are opened from several places (Home quick actions, an advisor shortcut,
  // My Farm, the tool browser) so a single static parent would send farmers to
  // the wrong screen.
  const [moduleBack, setModuleBack] = useState("home");

  const [profileOpen, setProfileOpen] = useState(false);

  const navigate = useCallback((next) => {
    setScreen(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openModule = useCallback((module, backTo = "home") => {
    setSelectedModule(module);
    setModuleBack(backTo);
    setScreen("module");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openLanguages = useCallback(() => setLanguageOpen(true), []);

  const handleLanguageSelect = useCallback(
    (next) => {
      changeLanguage(next);
      setLanguageOpen(false);
    },
    [changeLanguage],
  );

  /** Called by LoginScreen / RegisterScreen once auth succeeds. */
  const handleLogin = useCallback(
    (userData) => {
      // Capture the Supabase access token for protected backend requests.
      setAuthToken(userData?.access_token);
      saveUser(userData);
      setUser(userData);
      // A signed-in user's saved account preference wins over the device
      // default (but only if it is one of the two supported languages).
      const accountLanguage = normalizeLanguage(userData?.language);
      if (accountLanguage && accountLanguage !== language) {
        changeLanguage(accountLanguage);
      }
      navigate("home");
    },
    [navigate, language, changeLanguage],
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
          const prev = screen === "module" ? moduleBack : BACK_MAP[screen];
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
  }, [screen, profileOpen, languageOpen, moduleBack]);

  // ── Auth screens (no desktop nav / bottom nav) ────────────────────────────
  if (screen === "login") {
    return (
      <Suspense fallback={<ScreenLoader label={t("common.loadingSignIn")} />}>
        <LoginScreen navigate={navigate} onLogin={handleLogin} />
      </Suspense>
    );
  }
  if (screen === "register") {
    return (
      <Suspense fallback={<ScreenLoader label={t("common.loadingSignUp")} />}>
        <RegisterScreen navigate={navigate} onLogin={handleLogin} />
      </Suspense>
    );
  }

  // ── Main app ──────────────────────────────────────────────────────────────
  // Keep the correct bottom-nav tab lit while a module is open, so the section
  // the tool belongs to stays highlighted.
  const activeTab =
    screen === "module"
      ? navKeyForSection(moduleByKey(selectedModule)?.section)
      : screen;

  return (
    <LocationProvider>
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
          activeNav={activeTab}
          onAssistant={() => navigate("chat")}
          onNavigate={navigate}
          onOpen={(key) => openModule(key, "more")}
          user={user}
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
          {screen === "farm" && (
            <FarmScreen
              navigate={navigate}
              openModule={(key) => openModule(key, "farm")}
            />
          )}
          {screen === "advisor" && (
            <AdvisorScreen
              navigate={navigate}
              openModule={(key) => openModule(key, "advisor")}
              user={user}
            />
          )}
          {screen === "insights" && (
            <InsightsScreen
              navigate={navigate}
              openModule={(key) => openModule(key, "insights")}
              user={user}
            />
          )}
          {screen === "history" && (
            <HistoryScreen
              navigate={navigate}
              openModule={(key) => openModule(key, "history")}
            />
          )}
          {screen === "more" && (
            <ScreenShell active="more" navigate={navigate}>
              <ModuleHub
                onBack={() => navigate("home")}
                onOpen={(key) => openModule(key, "more")}
                user={user}
              />
            </ScreenShell>
          )}
          {screen === "module" && (
            <ScreenShell active={activeTab} navigate={navigate}>
              <ModuleScreen
                currentLanguage={language}
                moduleKey={selectedModule}
                onAsk={() => navigate("chat")}
                onBack={() => navigate(moduleBack)}
                onLanguage={changeLanguage}
                user={user}
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
    </LocationProvider>
  );
}
