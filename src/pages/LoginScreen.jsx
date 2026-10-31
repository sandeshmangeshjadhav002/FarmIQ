import { useState } from "react";
import { useTranslation } from "react-i18next";

import { API_BASE_URL } from "@/config/api";
import Icon from "@/components/common/Icon";
import Logo from "@/components/common/Logo";
import TextInput from "@/components/common/TextInput";
import { PrimaryButton, SecondaryButton } from "@/components/common/Button";

/**
 * Login screen — auth gate, no BottomNavigation.
 * Users sign in with their registered mobile number + password.
 *
 * @param {object}   props
 * @param {Function} props.navigate  - Navigate to a screen by key.
 * @param {Function} props.onLogin   - Called with user data on successful login.
 */
export default function LoginScreen({ navigate, onLogin }) {
  const { t } = useTranslation();
  const [countryCode, setCountryCode] = useState("+91");
  const [mobile,      setMobile]      = useState("");
  const [password,    setPassword]    = useState("");
  const [showPass,    setShowPass]    = useState(false);
  const [loading,     setLoading]     = useState(false);
  const [errors,      setErrors]      = useState({});
  const [toast,       setToast]       = useState(null);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  const validate = () => {
    const errs = {};
    if (!mobile.trim())
      errs.mobile = t("auth.login.errors.mobileRequired");
    else if (!/^\d{7,15}$/.test(mobile.trim()))
      errs.mobile = t("auth.login.errors.mobileInvalid");
    if (!password)
      errs.password = t("auth.login.errors.passwordRequired");
    return errs;
  };

  const handleLogin = async () => {
    // Re-entrancy guard: the button also gets `pointer-events-none` while
    // loading, but that does not stop a second Enter keypress on an input, so
    // the request itself must be the thing that is gated.
    if (loading) return;

    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mobile:   `${countryCode}${mobile.trim()}`,
          password,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        showToast("success", t("auth.login.toast.welcome", { name: data.full_name }));
        setTimeout(() => onLogin(data), 1500);
        return; // keep the button disabled until the redirect happens
      } else if (res.status === 401) {
        setErrors({ password: t("auth.login.errors.invalidCredentials") });
      } else {
        showToast(
          "error",
          data.detail ?? t("auth.login.toast.failed"),
        );
      }
    } catch {
      showToast("error", t("auth.login.toast.connect"));
    }
    setLoading(false);
  };

  const countryCodes = [
    { code: "+91",  label: "🇮🇳 +91"  },
    { code: "+1",   label: "🇺🇸 +1"   },
    { code: "+44",  label: "🇬🇧 +44"  },
    { code: "+61",  label: "🇦🇺 +61"  },
    { code: "+27",  label: "🇿🇦 +27"  },
    { code: "+234", label: "🇳🇬 +234" },
    { code: "+254", label: "🇰🇪 +254" },
    { code: "+55",  label: "🇧🇷 +55"  },
    { code: "+86",  label: "🇨🇳 +86"  },
    { code: "+880", label: "🇧🇩 +880" },
    { code: "+92",  label: "🇵🇰 +92"  },
  ];

  return (
    <main
      className="mx-auto flex min-h-dvh w-full flex-col overflow-hidden bg-[#F7F9F5] lg:max-w-[430px] lg:shadow-[0_0_60px_rgba(26,57,40,.12)] lg:rounded-[30px]"
      role="main"
    >
      {/* toast */}
      {toast && (
        <div
          aria-live="polite"
          role="alert"
          className={`fixed left-1/2 top-4 z-50 w-[calc(100%-2rem)] max-w-[350px] -translate-x-1/2 rounded-2xl px-4 py-3 text-[13px] font-semibold text-white shadow-lg ${
            toast.type === "success" ? "bg-[#216B45]" : "bg-[#C0392B]"
          }`}
        >
          <div className="flex items-center gap-2">
            <Icon name={toast.type === "success" ? "check" : "shield"} size={16} />
            {toast.message}
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-8 pt-6">
        {/* logo */}
        <div className="mb-8">
          <Logo />
        </div>

        {/* hero */}
        <div className="mb-7">
          <p className="mb-1 text-[13px] font-bold text-[#4D7A61]">
            {t("auth.login.welcomeBack")}
          </p>
          <h1 className="text-[28px] font-extrabold leading-[1.15] tracking-[-0.04em] text-[#17392A]">
            {t("auth.login.title")}
          </h1>
          <p className="mt-2 text-[13px] leading-5 text-[#718279]">
            {t("auth.login.subtitle")}
          </p>
        </div>

        {/* form card */}
        <div className="rounded-[24px] border border-[#E6EBE7] bg-white p-5 shadow-[0_5px_24px_rgba(31,57,44,.07)]">

          {/* mobile number */}
          <div className="mb-4">
            <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-[.08em] text-[#5A7266]">
              {t("auth.login.mobileLabel")}
            </label>
            <div className="flex gap-2">
              {/* country code selector */}
              <div className="relative flex-shrink-0">
                <select
                  aria-label={t("auth.login.countryCodeAria")}
                  className="h-13 appearance-none rounded-2xl border border-[#DFE7E1] bg-white pl-3 pr-8 text-[13px] font-semibold text-[#1E382B] shadow-[0_3px_12px_rgba(31,57,44,.04)] outline-none focus:border-[#216B45]"
                  value={countryCode}
                  onChange={(e) => setCountryCode(e.target.value)}
                >
                  {countryCodes.map((c) => (
                    <option key={c.code} value={c.code}>{c.label}</option>
                  ))}
                </select>
                <Icon
                  name="chevron"
                  size={13}
                  className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rotate-90 text-[#8A9A91]"
                />
              </div>
              {/* number input */}
              <label className="flex flex-1 h-13 items-center gap-3 rounded-2xl border border-[#DFE7E1] bg-white px-4 shadow-[0_3px_12px_rgba(31,57,44,.04)]">
                <Icon name="phone" size={19} className="shrink-0 text-[#7A8E82]" />
                <input
                  aria-label={t("auth.login.mobileAria")}
                  className="min-w-0 flex-1 bg-transparent text-[14px] text-[#1E382B] outline-none placeholder:text-[#8A9A91]"
                  inputMode="numeric"
                  maxLength={10}
                  size={10}
                  placeholder={t("auth.login.mobilePlaceholder")}
                  type="tel"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value.replace(/\D/g, "").slice(0, 10))}
                  onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                />
              </label>
            </div>
            {errors.mobile && (
              <p role="alert" className="mt-1 text-[11px] font-semibold text-[#C0392B]">
                {errors.mobile}
              </p>
            )}
          </div>

          {/* password */}
          <div className="mb-2">
            <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-[.08em] text-[#5A7266]">
              {t("auth.login.passwordLabel")}
            </label>
            <div className="relative">
              <TextInput
                icon="lock"
                type={showPass ? "text" : "password"}
                placeholder={t("auth.login.passwordPlaceholder")}
                value={password}
                onChange={setPassword}
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              />
              <button
                aria-label={showPass ? t("auth.login.hidePassword") : t("auth.login.showPassword")}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-[#8A9A91]"
                onClick={() => setShowPass((p) => !p)}
                type="button"
              >
                <Icon name={showPass ? "eye-off" : "eye"} size={18} />
              </button>
            </div>
            {errors.password && (
              <p role="alert" className="mt-1 text-[11px] font-semibold text-[#C0392B]">
                {errors.password}
              </p>
            )}
          </div>
        </div>

        {/* CTA */}
        <div className="mt-5">
          <PrimaryButton
            onClick={handleLogin}
            className={loading ? "opacity-70 pointer-events-none" : ""}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <Spinner />
                {t("auth.login.signingIn")}
              </span>
            ) : (
              <>
                <Icon name="leaf" size={18} />
                {t("auth.login.signIn")}
              </>
            )}
          </PrimaryButton>
        </div>

        {/* divider */}
        <div className="my-5 flex items-center gap-3">
          <div className="h-px flex-1 bg-[#E6EBE7]" />
          <span className="text-[11px] font-semibold text-[#9EAD9D]">
            {t("auth.login.divider")}
          </span>
          <div className="h-px flex-1 bg-[#E6EBE7]" />
        </div>

        {/* continue without account */}
        <SecondaryButton onClick={() => onLogin({ full_name: t("auth.login.guestName"), email: "—", mobile: "—", role: "farmer", created_at: null })}>
          <Icon name="sparkles" size={16} />
          {t("auth.login.continueAsGuest")}
        </SecondaryButton>

        {/* register link */}
        <p className="mt-6 text-center text-[13px] text-[#718279]">
          {t("auth.login.noAccount")}{" "}
          <button
            className="font-bold text-[#216B45] underline-offset-2 hover:underline"
            onClick={() => navigate("register")}
          >
            {t("auth.login.createAccount")}
          </button>
        </p>
      </div>
    </main>
  );
}

function Spinner() {
  return (
    <svg
      aria-hidden="true"
      className="h-4 w-4 animate-spin"
      fill="none"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
