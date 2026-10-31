import { useState } from "react";
import { useTranslation } from "react-i18next";

import useLanguage from "@/i18n/useLanguage";
import { API_BASE_URL } from "@/config/api";
import Icon from "@/components/common/Icon";
import Logo from "@/components/common/Logo";
import TextInput from "@/components/common/TextInput";
import { PrimaryButton } from "@/components/common/Button";

/**
 * Registration screen — no BottomNavigation (auth flow).
 *
 * Only the four things the account actually needs are asked for. The role
 * question was removed: a farmer should not have to classify themselves before
 * they can use the app, and "Farm Manager / Agricultural Expert" are choices
 * most people cannot answer confidently at signup. The backend defaults the
 * role to "farmer" and it can be changed later from the profile.
 *
 * @param {object}   props
 * @param {Function} props.navigate  - Navigate to a screen by key.
 * @param {Function} props.onLogin   - Called with user data on successful registration.
 */
export default function RegisterScreen({ navigate, onLogin }) {
  const { t } = useTranslation();
  // The language the visitor is already using — saved on the new account so a
  // Marathi speaker is not switched back to English after signing up.
  const { language } = useLanguage();

  // ── form fields ──────────────────────────────────────────────────────────
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [countryCode, setCountryCode] = useState("+91");
  const [mobile, setMobile] = useState("");
  const [password, setPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // ── async state ──────────────────────────────────────────────────────────
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [toast, setToast] = useState(null); // { type: "success"|"error", message }

  // ── helpers ──────────────────────────────────────────────────────────────
  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 5000);
  };

  const validate = () => {
    const errs = {};

    if (!fullName.trim()) errs.fullName = t("auth.register.errors.fullNameRequired");
    else if (fullName.trim().length < 2)
      errs.fullName = t("auth.register.errors.fullNameShort");

    if (!email.trim()) errs.email = t("auth.register.errors.emailRequired");
    else if (
      !/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email.trim())
    )
      errs.email = t("auth.register.errors.emailInvalid");

    if (!mobile.trim()) errs.mobile = t("auth.register.errors.mobileRequired");
    else if (!/^\d{10}$/.test(mobile.trim()))
      errs.mobile = t("auth.register.errors.mobileInvalid");

    if (!password) errs.password = t("auth.register.errors.passwordRequired");
    else if (password.length < 8)
      errs.password = t("auth.register.errors.passwordShort");
    else if (!/(?=.*[A-Z])/.test(password))
      errs.password = t("auth.register.errors.passwordUpper");
    else if (!/(?=.*\d)/.test(password))
      errs.password = t("auth.register.errors.passwordNumber");

    if (!agreed) errs.agreed = t("auth.register.errors.termsRequired");

    return errs;
  };

  const handleSubmit = async () => {
    // Re-entrancy guard — see LoginScreen: a CSS-disabled button does not stop
    // a repeat submit, so gate the request itself.
    if (loading) return;

    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim(),
          email: email.trim().toLowerCase(),
          mobile: `${countryCode}${mobile.trim()}`,
          // `role` is intentionally omitted — the backend defaults it to
          // "farmer" and the profile screen lets the user change it.
          password,
          // Persist the interface language chosen before signing up.
          language,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        showToast("success", t("auth.register.toast.created"));
        setTimeout(() => onLogin(data), 2000);
        return; // keep the button disabled until the redirect happens
      } else if (res.status === 409) {
        setErrors({
          email: data.detail ?? t("auth.register.errors.emailTaken"),
        });
      } else {
        showToast(
          "error",
          data.detail ?? t("auth.register.toast.failed"),
        );
      }
    } catch {
      showToast("error", t("auth.register.toast.connect"));
    }
    setLoading(false);
  };

  // ── country codes (common selection) ─────────────────────────────────────
  const countryCodes = [
    { code: "+91", label: "🇮🇳 +91" },
    { code: "+1", label: "🇺🇸 +1" },
    { code: "+44", label: "🇬🇧 +44" },
    { code: "+61", label: "🇦🇺 +61" },
    { code: "+27", label: "🇿🇦 +27" },
    { code: "+234", label: "🇳🇬 +234" },
    { code: "+254", label: "🇰🇪 +254" },
    { code: "+55", label: "🇧🇷 +55" },
    { code: "+86", label: "🇨🇳 +86" },
    { code: "+880", label: "🇧🇩 +880" },
    { code: "+92", label: "🇵🇰 +92" },
  ];

  // ── password strength ─────────────────────────────────────────────────────
  const getStrength = () => {
    if (!password) return 0;
    let s = 0;
    if (password.length >= 8) s++;
    if (/[A-Z]/.test(password)) s++;
    if (/\d/.test(password)) s++;
    if (/[^A-Za-z0-9]/.test(password)) s++;
    return s;
  };
  const strength = getStrength();
  const strengthLabels = [
    "",
    t("auth.register.strength.weak"),
    t("auth.register.strength.fair"),
    t("auth.register.strength.good"),
    t("auth.register.strength.strong"),
  ];
  const strengthColors = ["", "#E74C3C", "#E67E22", "#F1C40F", "#216B45"];

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <main
      className="mx-auto flex min-h-dvh w-full flex-col overflow-hidden bg-[#F7F9F5] lg:max-w-[430px] lg:shadow-[0_0_60px_rgba(26,57,40,.12)] lg:rounded-[30px]"
      role="main"
    >
      {/* ── toast notification ── */}
      {toast && (
        <div
          aria-live="polite"
          role="alert"
          className={`fixed left-1/2 top-4 z-50 w-[calc(100%-2rem)] max-w-[350px] -translate-x-1/2 rounded-2xl px-4 py-3 text-[13px] font-semibold text-white shadow-lg transition-all ${
            toast.type === "success" ? "bg-[#216B45]" : "bg-[#C0392B]"
          }`}
        >
          <div className="flex items-center gap-2">
            <Icon
              name={toast.type === "success" ? "check" : "shield"}
              size={16}
            />
            {toast.message}
          </div>
        </div>
      )}

      {/* ── scrollable content ── */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-8 pt-6">
        {/* header */}
        <div className="mb-6 flex items-center justify-between">
          <Logo />
          <button
            aria-label={t("auth.register.goBack")}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#DFE7E1] bg-white text-[#216B45] shadow-sm"
            onClick={() => navigate("login")}
          >
            <Icon name="arrow" size={18} className="rotate-180" />
          </button>
        </div>

        {/* hero text */}
        <div className="mb-6">
          <p className="mb-1 text-[13px] font-bold text-[#4D7A61]">
            {t("auth.register.getStarted")}
          </p>
          <h1 className="text-[26px] font-extrabold leading-[1.15] tracking-[-0.04em] text-[#17392A]">
            {t("auth.register.title")}
          </h1>
          <p className="mt-2 text-[13px] leading-5 text-[#718279]">
            {t("auth.register.subtitle")}
          </p>
        </div>

        {/* ── form card ── */}
        <div className="rounded-[24px] border border-[#E6EBE7] bg-white p-5 shadow-[0_5px_24px_rgba(31,57,44,.07)]">
          {/* full name */}
          <Field label={t("auth.register.fullName")} error={errors.fullName}>
            <TextInput
              icon="person"
              placeholder={t("auth.register.fullNamePlaceholder")}
              value={fullName}
              onChange={setFullName}
            />
          </Field>

          {/* email */}
          <Field label={t("auth.register.email")} error={errors.email}>
            <TextInput
              icon="mail"
              type="email"
              placeholder={t("auth.register.emailPlaceholder")}
              value={email}
              onChange={setEmail}
            />
          </Field>

          {/* mobile number */}
          <Field label={t("auth.register.mobileLabel")} error={errors.mobile}>
            <div className="flex gap-2">
              {/* country code selector */}
              <div className="relative flex-shrink-0">
                <select
                  aria-label={t("auth.register.countryCodeAria")}
                  className="h-13 appearance-none rounded-2xl border border-[#DFE7E1] bg-white pl-3 pr-8 text-[13px] font-semibold text-[#1E382B] shadow-[0_3px_12px_rgba(31,57,44,.04)] outline-none focus:border-[#216B45]"
                  value={countryCode}
                  onChange={(e) => setCountryCode(e.target.value)}
                >
                  {countryCodes.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
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
                <Icon
                  name="phone"
                  size={19}
                  className="shrink-0 text-[#7A8E82]"
                />
                <input
                  aria-label={t("auth.register.mobileAria")}
                  className="min-w-0 flex-1 bg-transparent text-[14px] text-[#1E382B] outline-none placeholder:text-[#8A9A91]"
                  inputMode="numeric"
                  maxLength={10}
                  size={10}
                  pattern="\d{10}"
                  placeholder={t("auth.register.mobilePlaceholder")}
                  type="tel"
                  value={mobile}
                  onChange={(e) =>
                    setMobile(e.target.value.replace(/\D/g, "").slice(0, 10))
                  }
                />
              </label>
            </div>
          </Field>

          {/* password */}
          <Field label={t("auth.register.passwordLabel")} error={errors.password}>
            <div className="relative">
              <TextInput
                icon="lock"
                type={showPassword ? "text" : "password"}
                placeholder={t("auth.register.passwordPlaceholder")}
                value={password}
                onChange={setPassword}
              />
              <button
                aria-label={showPassword ? t("auth.register.hidePassword") : t("auth.register.showPassword")}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-[#8A9A91]"
                onClick={() => setShowPassword((p) => !p)}
                type="button"
              >
                <Icon name={showPassword ? "eye-off" : "eye"} size={18} />
              </button>
            </div>
            {/* strength bar */}
            {password.length > 0 && (
              <div className="mt-2 space-y-1">
                <div className="flex gap-1">
                  {[1, 2, 3, 4].map((i) => (
                    <div
                      key={i}
                      className="h-1 flex-1 rounded-full transition-all"
                      style={{
                        background:
                          i <= strength ? strengthColors[strength] : "#E6EBE7",
                      }}
                    />
                  ))}
                </div>
                <p
                  className="text-[11px] font-semibold"
                  style={{ color: strengthColors[strength] }}
                >
                  {strengthLabels[strength]}
                </p>
              </div>
            )}
          </Field>

          {/* terms checkbox */}
          <div className="mt-1">
            <label className="flex cursor-pointer items-start gap-3">
              <span
                role="checkbox"
                aria-checked={agreed}
                tabIndex={0}
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition ${
                  agreed
                    ? "border-[#216B45] bg-[#216B45]"
                    : errors.agreed
                    ? "border-[#C0392B]"
                    : "border-[#C4D0C8]"
                }`}
                onClick={() => setAgreed((a) => !a)}
                onKeyDown={(e) => e.key === " " && setAgreed((a) => !a)}
              >
                {agreed && (
                  <Icon name="check" size={13} className="text-white" />
                )}
              </span>
              <span className="text-[12px] leading-5 text-[#718279]">
                {t("auth.register.termsLead")}
                <span className="font-semibold text-[#216B45]">
                  {t("auth.register.termsAndConditions")}
                </span>
                {t("auth.register.termsJoin")}
                <span className="font-semibold text-[#216B45]">
                  {t("auth.register.privacyPolicy")}
                </span>
                {t("auth.register.termsSuffix")}
              </span>
            </label>
            {errors.agreed && (
              <p className="mt-1 text-[11px] font-semibold text-[#C0392B]">
                {errors.agreed}
              </p>
            )}
          </div>
        </div>

        {/* ── submit ── */}
        <div className="mt-5">
          <PrimaryButton
            onClick={handleSubmit}
            className={loading ? "opacity-70 pointer-events-none" : ""}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <Spinner />
                {t("auth.register.creatingAccount")}
              </span>
            ) : (
              <>
                <Icon name="sparkles" size={18} />
                {t("auth.register.createAccount")}
              </>
            )}
          </PrimaryButton>
        </div>

        {/* ── sign in link ── */}
        <p className="mt-5 text-center text-[13px] text-[#718279]">
          {t("auth.register.haveAccount")}{" "}
          <button
            className="font-bold text-[#216B45] underline-offset-2 hover:underline"
            onClick={() => navigate("login")}
          >
            {t("auth.register.signIn")}
          </button>
        </p>
      </div>
    </main>
  );
}

// ── tiny sub-components ────────────────────────────────────────────────────

/** Labelled form field with optional error message. */
function Field({ label, error, children }) {
  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-[.08em] text-[#5A7266]">
        {label}
      </label>
      {children}
      {error && (
        <p
          role="alert"
          className="mt-1 text-[11px] font-semibold text-[#C0392B]"
        >
          {error}
        </p>
      )}
    </div>
  );
}

/** Small inline loading spinner. */
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
        cx="12"
        cy="12"
        r="10"
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
