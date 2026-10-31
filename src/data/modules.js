/**
 * Structural data for FarmIQ's navigation and modules.
 *
 * Every user-facing string lives in the translation files
 * (``src/i18n/locales/{en,mr}/*.json``) rather than here, so the same
 * structure serves both languages. The keys below are stable identifiers —
 * do not rename them, they are also used in the API and database layers.
 *
 * Display copy is looked up by the component that renders it:
 *
 *   sections       → t(`sections.${key}.label`) / `.short`
 *   moduleCatalog  → t(`modules.${key}.title`)   / `.short`
 *   quickActions   → t(`quickActions.${target}.title`) / `.subtitle`
 *   navItems       → t(`nav.${key}`)
 */

/**
 * The six top-level sections FarmIQ is organised into.
 *
 * Every module belongs to exactly one section. ``home`` owns no browseable
 * tools — it is the overview screen itself, plus the alerts surface — so the
 * hub lists it only when it has modules (see ``browsableModules``).
 */
export const sections = [
  { key: "home", icon: "home" },
  { key: "farm", icon: "farm" },
  { key: "advisor", icon: "sparkles" },
  { key: "insights", icon: "chart" },
  { key: "knowledge", icon: "book" },
  { key: "admin", icon: "settings" },
];

/** Look up a section descriptor by key. */
export const sectionByKey = (key) => sections.find((item) => item.key === key);

/**
 * Which bottom-navigation tab a section belongs to.
 *
 * The Knowledge Centre and Settings sections have no tab of their own; they are
 * reached through "More", so opening one of their modules keeps "More" lit
 * instead of highlighting an unrelated tab.
 */
const SECTION_TO_NAV = {
  home: "home",
  farm: "farm",
  advisor: "advisor",
  insights: "insights",
  knowledge: "more",
  admin: "more",
};

/** Active bottom-nav key for a section (defaults to Home). */
export const navKeyForSection = (section) => SECTION_TO_NAV[section] ?? "home";

/**
 * Role allowed to open the administrative tools.
 *
 * Mirrors the roles the backend validates (VALID_ROLES in
 * backend/app/config.py). FarmIQ has no dedicated administrator role, so the
 * technical/advisory role is treated as the authorised one.
 */
export const ADMIN_ROLE = "agricultural_expert";

/** True when this user may open administrative/MLOps modules. */
export const canAccessAdminTools = (user) => user?.role === ADMIN_ROLE;

/**
 * Master catalog of every FarmIQ module/tool.
 * Used by ModuleHub (browsing) and ModuleScreen (rendering).
 *
 * ``section``  — the top-level section this module belongs to (see ``sections``).
 * ``contextual`` — reachable from within its section's screens rather than as a
 *                  primary destination in the browse grid.
 * ``adminOnly``  — hidden unless the signed-in role is ``ADMIN_ROLE``.
 */
export const moduleCatalog = [
  {
    key: "farm-management",
    section: "farm",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "farm",
  },
  {
    key: "crop-recommendation",
    section: "advisor",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "crop",
  },
  {
    key: "fertilizer",
    section: "advisor",
    color: "bg-[#FFF2DA] text-[#986313]",
    icon: "flask",
  },
  {
    key: "organic-farming",
    section: "advisor",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "leaf",
  },
  {
    key: "drought-management",
    section: "advisor",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "drought",
  },
  {
    key: "irrigation",
    section: "advisor",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "drop",
  },
  {
    key: "soil",
    section: "farm",
    color: "bg-[#EFEBDD] text-[#76683A]",
    icon: "soil",
  },
  {
    key: "sensors",
    section: "farm",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "signal",
  },
  {
    key: "sensor-simulator",
    section: "farm",
    contextual: true,
    color: "bg-[#FFF2DA] text-[#986313]",
    icon: "signal",
  },
  {
    key: "yield",
    section: "insights",
    color: "bg-[#EAF1DE] text-[#657638]",
    icon: "chart",
  },
  {
    key: "market",
    section: "insights",
    color: "bg-[#F2EAF7] text-[#745088]",
    icon: "market",
  },
  {
    key: "image-analysis",
    section: "advisor",
    color: "bg-[#FCEBDD] text-[#A7602A]",
    icon: "camera",
  },
  {
    key: "knowledge",
    section: "knowledge",
    color: "bg-[#E9F1EA] text-[#3C6A4D]",
    icon: "book",
  },
  {
    key: "schemes",
    section: "knowledge",
    color: "bg-[#E9F1EA] text-[#3C6A4D]",
    icon: "shield",
  },
  {
    key: "calendar",
    section: "farm",
    color: "bg-[#E8EEF8] text-[#4F6590]",
    icon: "calendar",
  },
  {
    key: "alerts",
    section: "home",
    color: "bg-[#FCE9E5] text-[#A55243]",
    icon: "bell",
  },
  {
    key: "reports",
    section: "insights",
    color: "bg-[#E9EAF7] text-[#575E95]",
    icon: "report",
  },
  {
    key: "devices",
    section: "farm",
    contextual: true,
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "device",
  },
  {
    key: "settings",
    section: "admin",
    color: "bg-[#EDF1EE] text-[#52665B]",
    icon: "settings",
  },
  {
    key: "mlops",
    section: "admin",
    adminOnly: true,
    color: "bg-[#E9EAF7] text-[#575E95]",
    icon: "model",
  },
  {
    key: "hackathon-demo",
    section: "admin",
    adminOnly: true,
    color: "bg-[#FFF8EA] text-[#8A6D2B]",
    icon: "sparkles",
  },
  {
    key: "admin",
    section: "admin",
    adminOnly: true,
    color: "bg-[#F2EAF7] text-[#745088]",
    icon: "shield",
  },
];

/** Look up a module descriptor by key. */
export const moduleByKey = (key) =>
  moduleCatalog.find((item) => item.key === key);

/**
 * Modules a user should see as primary destinations.
 *
 * Contextual modules (device configuration, sensor simulation) stay in the
 * catalogue so their routes keep working, but they are opened from the screen
 * that owns them rather than listed as standalone tools.
 */
export function browsableModules(user, { includeContextual = false } = {}) {
  return moduleCatalog.filter(
    (item) =>
      (includeContextual || !item.contextual) &&
      (!item.adminOnly || canAccessAdminTools(user)),
  );
}

/**
 * Quick action cards shown on the Home screen.
 * ``target`` is the module key each card opens (see ``moduleCatalog``).
 */
export const quickActions = [
  {
    color: "bg-[#E8F3E9] text-[#287047]",
    icon: "crop",
    target: "crop-recommendation",
  },
  {
    color: "bg-[#E7F4F7] text-[#31768A]",
    icon: "droplet",
    target: "irrigation",
  },
  {
    color: "bg-[#FFF3D9] text-[#A16912]",
    icon: "fertilizer",
    target: "fertilizer",
  },
  {
    color: "bg-[#F2EAF8] text-[#76518D]",
    icon: "market",
    target: "market",
  },
];

/**
 * Bottom-navigation destinations.
 *
 * Five entries is the most that fits legibly at 360px. The Knowledge Centre
 * and Settings & Administration sections are reached through "More", which
 * opens the section-grouped tool browser.
 */
export const navItems = [
  { key: "home", icon: "home" },
  { key: "farm", icon: "farm" },
  { key: "advisor", icon: "bot" },
  { key: "insights", icon: "chart" },
  { key: "more", icon: "menu" },
];

/**
 * Demo reminder state for the Farming Calendar module.
 *
 * Only the mutable flags live here; the titles and dates come from
 * ``t("data.defaultReminders")`` so they follow the selected language.
 */
export const defaultReminders = [
  { id: 1, done: false },
  { id: 2, done: false },
  { id: 3, done: true },
];
