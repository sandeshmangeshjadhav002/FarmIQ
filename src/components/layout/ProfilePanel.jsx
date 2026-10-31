import { useState } from "react";
import { useTranslation } from "react-i18next";
import Icon from "@/components/common/Icon";
import { apiPatch } from "@/lib/apiClient";

/** Roles the backend accepts (mirrors VALID_ROLES in backend/app/schemas.py). */
const ROLE_OPTIONS = [
  { value: "farmer", labelKey: "roles.farmer" },
  { value: "farm_manager", labelKey: "roles.farm_manager" },
  { value: "agricultural_expert", labelKey: "roles.agricultural_expert" },
];

/**
 * ProfilePanel — a slide-up sheet showing logged-in user info.
 *
 * Features:
 *  - Displays full name, email, mobile, role, and member-since date.
 *  - Edit mode lets the user update their full name and role. Role is editable
 *    here because the signup form no longer asks for it (everyone starts as
 *    "farmer"), so this is the only way to become a Farm Manager or Expert.
 *  - Logout button at the bottom.
 *
 * @param {object}   props
 * @param {object}   props.user       - User object from login response.
 * @param {Function} props.onClose    - Close the panel.
 * @param {Function} props.onLogout   - Log out and return to login screen.
 * @param {Function} props.onUpdate   - Called with updated user object after save.
 */
export default function ProfilePanel({ user, onClose, onLogout, onUpdate }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [role, setRole] = useState(user?.role ?? "farmer");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSave = async () => {
    if (!fullName.trim() || fullName.trim().length < 2) {
      showToast("error", t("profile.nameTooShort"));
      return;
    }
    setSaving(true);
    try {
      // Persist to FastAPI → Supabase. Returns the updated profile. Only the
      // changed fields are sent so an unchanged role is never re-submitted.
      const payload = { full_name: fullName.trim() };
      if (role !== user?.role) payload.role = role;
      const updated = await apiPatch("/api/users/me", payload);
      onUpdate({ ...user, ...updated, full_name: fullName.trim(), role });
      showToast("success", t("profile.updated"));
      setEditing(false);
    } catch (err) {
      showToast("error", err.message || t("profile.updateFailed"));
      setFullName(user?.full_name ?? "");
      setRole(user?.role ?? "farmer");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setFullName(user?.full_name ?? "");
    setRole(user?.role ?? "farmer");
    setEditing(false);
  };

  /** Format a role key like "farm_manager" → "Farm Manager" */
  const formatRole = (value = "") =>
    value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  /** Localised role label, falling back to the derived English label. */
  const roleLabel = (value) =>
    t(`roles.${value}`, { defaultValue: formatRole(value) });

  /** Format ISO date to readable string */
  const formatDate = (iso = "") => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleDateString("en-IN", {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return "—";
    }
  };

  /** Generate initials avatar from full name */
  const initials = (user?.full_name ?? "?")
    .trim()
    .split(/\s+/)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .slice(0, 2)
    .join("");

  return (
    <>
      {/* backdrop */}
      <div
        className="absolute inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* panel — slides up from the bottom of the content column */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("profile.aria")}
        className="absolute bottom-0 left-0 right-0 z-50 rounded-t-[28px] bg-white/70 shadow-[0_-8px_40px_rgba(26,57,40,.18)] backdrop-blur-2xl border-t border-white/30 animate-slide-up"
      >
        {/* drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="h-1 w-10 rounded-full bg-[#C9D9CD]" />
        </div>

        {/* toast */}
        {toast && (
          <div
            aria-live="polite"
            role="alert"
            className={`mx-5 mb-3 flex items-center gap-2 rounded-2xl px-4 py-2.5 text-[12px] font-semibold text-white ${
              toast.type === "success" ? "bg-[#216B45]" : "bg-[#C0392B]"
            }`}
          >
            <Icon
              name={toast.type === "success" ? "check" : "shield"}
              size={14}
            />
            {toast.message}
          </div>
        )}

        <div className="px-5 pb-6 pt-2">
          {/* header row */}
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-[18px] font-extrabold tracking-tight text-[#17392A]">
              {t("profile.title")}
            </h2>
            <button
              onClick={onClose}
              aria-label={t("common.close")}
              className="grid h-8 w-8 place-items-center rounded-full bg-[#EBF1EC] text-[#3F5A4B]"
            >
              <Icon name="plus" size={16} className="rotate-45" />
            </button>
          </div>

          {/* avatar + name card */}
          <div className="mb-5 flex items-center gap-4 rounded-[20px] border border-white/30 bg-white/40 p-4 shadow-[0_4px_16px_rgba(31,57,44,.06)] backdrop-blur-md">
            <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-[#216B45] text-xl font-extrabold text-white select-none">
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              {editing ? (
                <input
                  autoFocus
                  className="w-full rounded-xl border border-[#216B45] bg-[#F0F7F2] px-3 py-1.5 text-[15px] font-bold text-[#17392A] outline-none"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSave()}
                  aria-label={t("profile.fullNameAria")}
                />
              ) : (
                <p className="truncate text-[16px] font-extrabold text-[#17392A]">
                  {user?.full_name}
                </p>
              )}
              <p className="mt-0.5 text-[11px] font-semibold text-[#5A7A68]">
                {roleLabel(user?.role)}
              </p>
            </div>
            {!editing && (
              <button
                onClick={() => setEditing(true)}
                aria-label={t("profile.editName")}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#EBF4EE] text-[#216B45]"
              >
                <Icon name="edit" size={16} />
              </button>
            )}
          </div>

          {/* edit action buttons */}
          {editing && (
            <div className="mb-4 flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-[#216B45] py-2.5 text-[13px] font-bold text-white disabled:opacity-60"
              >
                {saving ? <Spinner /> : <Icon name="check" size={15} />}
                {t("common.save")}
              </button>
              <button
                onClick={handleCancel}
                className="flex flex-1 items-center justify-center gap-2 rounded-2xl border border-[#DDE8DF] bg-white py-2.5 text-[13px] font-bold text-[#3F5A4B]"
              >
                {t("common.cancel")}
              </button>
            </div>
          )}

          {/* info rows */}
          <div className="mb-5 divide-y divide-white/20 rounded-[20px] border border-white/30 bg-white/40 shadow-[0_4px_16px_rgba(31,57,44,.04)] backdrop-blur-md">
            <InfoRow icon="mail" label={t("profile.email")} value={user?.email} />
            <InfoRow
              icon="phone"
              label={t("profile.mobile")}
              value={user?.mobile}
            />
            {editing ? (
              <div className="flex items-center gap-3 px-4 py-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#EBF4EE] text-[#4D7A61]">
                  <Icon name="shield" size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <label
                    htmlFor="profile-role"
                    className="text-[10px] font-bold uppercase tracking-[.08em] text-[#8A9E92]"
                  >
                    {t("profile.role")}
                  </label>
                  <select
                    id="profile-role"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-[#DDE8DF] bg-white px-2 py-1.5 text-[13px] font-semibold text-[#1D382A] outline-none focus:border-[#216B45]"
                  >
                    {ROLE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {t(o.labelKey)}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-[9px] leading-4 text-[#8A9E92]">
                    {t("profile.roleHint")}
                  </p>
                </div>
              </div>
            ) : (
              <InfoRow
                icon="shield"
                label={t("profile.role")}
                value={roleLabel(user?.role)}
              />
            )}
            <InfoRow
              icon="clock"
              label={t("profile.memberSince")}
              value={formatDate(user?.created_at)}
            />
          </div>

          {/* logout */}
          <button
            onClick={onLogout}
            className="flex w-full items-center justify-center gap-2.5 rounded-2xl border border-[#F5C6C2] bg-[#FEF3F2] py-3.5 text-[14px] font-bold text-[#C0392B] transition hover:bg-[#fde8e6] active:scale-[.98]"
          >
            <Icon name="logout" size={18} />
            {t("profile.logOut")}
          </button>
        </div>
      </div>
    </>
  );
}

function InfoRow({ icon, label, value }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#EBF4EE] text-[#4D7A61]">
        <Icon name={icon} size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#8A9E92]">
          {label}
        </p>
        <p className="truncate text-[13px] font-semibold text-[#1D382A]">
          {value ?? "—"}
        </p>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      aria-hidden="true"
      className="h-4 w-4 animate-spin"
      fill="none"
      viewBox="0 0 24 24"
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
