/**
 * The six top-level sections FarmIQ is organised into.
 *
 * Every module belongs to exactly one section. ``home`` owns no browseable
 * tools — it is the overview screen itself, plus the alerts surface — so the
 * hub lists it only when it has modules (see ``browsableModules``).
 */
export const sections = [
  {
    key: "home",
    label: "Home",
    short: "Overview, today's plan and alerts",
    icon: "home",
  },
  {
    key: "farm",
    label: "My Farm",
    short: "Farms, crops, soil, sensors and devices",
    icon: "farm",
  },
  {
    key: "advisor",
    label: "AI Farm Advisor",
    short: "Guidance from the ML models and knowledge base",
    icon: "sparkles",
  },
  {
    key: "insights",
    label: "Insights & Analytics",
    short: "Yield, market, reports and prediction history",
    icon: "chart",
  },
  {
    key: "knowledge",
    label: "Knowledge Centre",
    short: "Trusted guides and government schemes",
    icon: "book",
  },
  {
    key: "admin",
    label: "Settings & Administration",
    short: "Profile, devices, roles and model health",
    icon: "settings",
  },
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
    title: "Farm Management",
    short: "Farms, fields, crops and growth stages",
    section: "farm",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "farm",
  },
  {
    key: "crop-recommendation",
    title: "Crop Recommendation",
    short: "Find crops suited to your field",
    section: "advisor",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "crop",
  },
  {
    key: "fertilizer",
    title: "Fertilizer Recommendation",
    short: "Nutrient guidance and precautions",
    section: "advisor",
    color: "bg-[#FFF2DA] text-[#986313]",
    icon: "flask",
  },
  {
    key: "organic-farming",
    title: "Organic Farming Advisor",
    short: "Compare conventional, organic and integrated methods",
    section: "advisor",
    color: "bg-[#E6F3E8] text-[#216B45]",
    icon: "leaf",
  },
  {
    key: "drought-management",
    title: "Drought Management",
    short: "Water conservation and dry-spell guidance",
    section: "advisor",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "drought",
  },
  {
    key: "irrigation",
    title: "Smart Irrigation",
    short: "Water at the right time and amount",
    section: "advisor",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "drop",
  },
  {
    key: "soil",
    title: "Soil Health",
    short: "pH, EC, moisture and NPK readings",
    section: "farm",
    color: "bg-[#EFEBDD] text-[#76683A]",
    icon: "soil",
  },
  {
    key: "sensors",
    title: "IoT Sensor Monitoring",
    short: "Live and historical farm readings",
    section: "farm",
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "signal",
  },
  {
    key: "sensor-simulator",
    title: "Sensor Simulator",
    short: "Test the pipeline with demo readings",
    section: "farm",
    contextual: true,
    color: "bg-[#FFF2DA] text-[#986313]",
    icon: "signal",
  },
  {
    key: "yield",
    title: "Yield Prediction",
    short: "Estimate production with uncertainty",
    section: "insights",
    color: "bg-[#EAF1DE] text-[#657638]",
    icon: "chart",
  },
  {
    key: "market",
    title: "Market Intelligence",
    short: "Prices, trends, forecasts and alerts",
    section: "insights",
    color: "bg-[#F2EAF7] text-[#745088]",
    icon: "market",
  },
  {
    key: "image-analysis",
    title: "Crop Image Analysis",
    short: "Check crop photos for possible issues",
    section: "advisor",
    color: "bg-[#FCEBDD] text-[#A7602A]",
    icon: "camera",
  },
  {
    key: "knowledge",
    title: "Knowledge Center",
    short: "Trusted agricultural guides and sources",
    section: "knowledge",
    color: "bg-[#E9F1EA] text-[#3C6A4D]",
    icon: "book",
  },
  {
    key: "schemes",
    title: "Government Schemes",
    short: "Verified subsidy and support schemes",
    section: "knowledge",
    color: "bg-[#E9F1EA] text-[#3C6A4D]",
    icon: "shield",
  },
  {
    key: "calendar",
    title: "Farming Calendar",
    short: "Activities, tasks and reminders",
    section: "farm",
    color: "bg-[#E8EEF8] text-[#4F6590]",
    icon: "calendar",
  },
  {
    key: "alerts",
    title: "Alerts & Notifications",
    short: "Weather, sensor and market updates",
    section: "home",
    color: "bg-[#FCE9E5] text-[#A55243]",
    icon: "bell",
  },
  {
    key: "reports",
    title: "Reports & Analytics",
    short: "Farm performance and saved advice",
    section: "insights",
    color: "bg-[#E9EAF7] text-[#575E95]",
    icon: "report",
  },
  {
    key: "devices",
    title: "Device Management",
    short: "Pair, assign and configure devices",
    section: "farm",
    contextual: true,
    color: "bg-[#E5F3F7] text-[#28778A]",
    icon: "device",
  },
  {
    key: "settings",
    title: "Profile & Settings",
    short: "Language, units and preferences",
    section: "admin",
    color: "bg-[#EDF1EE] text-[#52665B]",
    icon: "settings",
  },
  {
    key: "mlops",
    title: "MLOps Dashboard",
    short: "Models, data quality and API health",
    section: "admin",
    adminOnly: true,
    color: "bg-[#E9EAF7] text-[#575E95]",
    icon: "model",
  },
  {
    key: "hackathon-demo",
    title: "Hackathon Demo Mode",
    short: "Interactive synthetic farm for judges",
    section: "admin",
    adminOnly: true,
    color: "bg-[#FFF8EA] text-[#8A6D2B]",
    icon: "sparkles",
  },
  {
    key: "admin",
    title: "Administration & Roles",
    short: "Users, permissions and audit activity",
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
 * Static data for each generic module screen (metrics, summary rows).
 * Modules with custom UIs (farm-management, image-analysis, calendar,
 * knowledge, settings, devices) are handled by their own components.
 */
export const moduleConfigs = {
  "crop-recommendation": {
    title: "Recommended for your field",
    detail: "Based on loamy soil, Nashik climate and October sowing.",
    metrics: [
      ["Top match", "Chickpea", "92% suitability"],
      ["Water need", "Low", "Compared with current crop"],
      ["Duration", "105 days", "Expected harvest"],
    ],
    rows: [
      ["Chickpea", "High suitability", "Low water • Good market"],
      ["Sorghum", "Good suitability", "Drought tolerant"],
      ["Wheat", "Moderate suitability", "Needs more irrigation"],
    ],
  },
  fertilizer: {
    title: "Nutrient guidance",
    detail: "Guidance uses the latest available soil sample.",
    metrics: [
      ["Nitrogen", "Low", "184 kg/ha"],
      ["Phosphorus", "Medium", "22 kg/ha"],
      ["Potassium", "Good", "318 kg/ha"],
    ],
    rows: [
      ["Urea", "18 kg / acre", "Split into two applications"],
      ["DAP", "12 kg / acre", "Apply near root zone"],
      ["Precaution", "Wear gloves", "Do not apply before heavy rain"],
    ],
  },
  irrigation: {
    title: "Irrigation recommendation",
    detail: "Wait today. Water lightly tomorrow before 8 AM.",
    metrics: [
      ["Soil moisture", "62%", "Live sensor reading"],
      ["Rain chance", "20%", "Next 24 hours"],
      ["Water tank", "78%", "About 2,340 litres"],
    ],
    rows: [
      ["Tomato field", "Tomorrow, 6:30 AM", "25 minutes • Drip"],
      ["Last irrigation", "2 days ago", "420 litres"],
      ["Growth stage", "Flowering", "Avoid water stress"],
    ],
  },
  soil: {
    title: "Soil health summary",
    detail: "Most readings are healthy. Nitrogen needs attention.",
    metrics: [
      ["pH", "6.7", "Optimal"],
      ["EC", "0.82", "dS/m • Normal"],
      ["Temperature", "24.8°C", "Sensor reading"],
    ],
    rows: [
      ["Nitrogen (N)", "184 kg/ha", "Low"],
      ["Phosphorus (P)", "22 kg/ha", "Medium"],
      ["Potassium (K)", "318 kg/ha", "Good"],
      ["Moisture", "62%", "Optimal"],
    ],
  },
  sensors: {
    title: "Sensor readings",
    detail: "ESP32 Field Hub • Last synced 2 minutes ago.",
    metrics: [
      ["Online", "3 of 4", "One device offline"],
      ["Data points", "1,248", "Received today"],
      ["Uptime", "98.7%", "Last 30 days"],
    ],
    rows: [
      ["Soil moisture S1", "62%", "Live reading"],
      ["Air temperature", "27°C", "Live reading"],
      ["Humidity", "71%", "Live reading"],
      ["Tank level S4", "Unavailable", "Device offline"],
    ],
  },
  yield: {
    title: "Tomato yield estimate",
    detail: "Prediction range reflects weather and crop uncertainty.",
    metrics: [
      ["Estimated yield", "18.4 t", "Per 2.5 acres"],
      ["Expected income", "₹4.2 L", "At current demo price"],
      ["Confidence", "± 2.1 t", "Moderate uncertainty"],
    ],
    rows: [
      ["Plant health", "Strong", "Positive factor"],
      ["Water consistency", "Good", "Positive factor"],
      ["Heat risk", "Medium", "May reduce fruit set"],
    ],
  },
  market: {
    title: "Nashik market outlook",
    detail: "Reported prices are delayed demonstration data.",
    metrics: [
      ["Tomato", "₹2,450", "Per quintal"],
      ["7-day trend", "+8%", "Upward"],
      ["Forecast", "₹2,520", "Next week estimate"],
    ],
    rows: [
      ["Nashik APMC", "₹2,450", "Reported 10:00 AM"],
      ["Pune Market", "₹2,380", "Reported yesterday"],
      ["Mumbai APMC", "₹2,610", "Reported yesterday"],
    ],
  },
  reports: {
    title: "Farm performance",
    detail: "Preview for 1–31 October • Green Valley Farm.",
    metrics: [
      ["Water used", "8,420 L", "12% lower"],
      ["Farm tasks", "24 / 27", "89% complete"],
      ["Sensor uptime", "98.7%", "4 connected"],
    ],
    rows: [
      ["Farm activity report", "October 2025", "12 pages"],
      ["Irrigation history", "Last 30 days", "8 events"],
      ["Saved AI advice", "All time", "14 items"],
      ["Yield estimates", "Current season", "3 crops"],
    ],
  },
  mlops: {
    title: "Production model health",
    detail: "Technical administrator view • Not shown to farmers.",
    metrics: [
      ["API health", "99.96%", "Healthy"],
      ["P95 latency", "284 ms", "Within target"],
      ["Data drift", "3.2%", "Low"],
    ],
    rows: [
      ["crop-recommender", "v2.4.1", "Production • Healthy"],
      ["yield-forecaster", "v1.8.0", "Production • Monitor"],
      ["disease-vision", "v3.1.2", "Staged • Evaluating"],
      ["Sensor ingestion", "18.2K/min", "No backlog"],
      ["Training run #481", "F1 0.924", "Completed 2h ago"],
      ["Error logs", "4 warnings", "No critical errors"],
    ],
  },
  admin: {
    title: "People and access",
    detail: "Manage access without exposing technical tools to farmers.",
    metrics: [
      ["Users", "248", "12 active now"],
      ["Farmers", "226", "Standard role"],
      ["Admins", "4", "Full access"],
    ],
    rows: [
      ["Anita Patil", "Farm Manager", "Green Valley Farm"],
      ["Ravi Kumar", "Agronomist", "Advisory access"],
      ["Meera Shah", "Administrator", "All workspaces"],
      ["Pending invitations", "3 users", "Expires in 5 days"],
    ],
  },
};

/** Multilingual options for the Settings panel language picker. */
export const settingsLanguages = [
  ["English", "English"],
  ["हिन्दी (Hindi)", "Hindi"],
  ["मराठी (Marathi)", "Marathi"],
  ["తెలుగు (Telugu)", "Telugu"],
  ["தமிழ் (Tamil)", "Tamil"],
  ["ಕನ್ನಡ (Kannada)", "Kannada"],
  ["ગુજરાતી (Gujarati)", "Gujarati"],
  ["বাংলা (Bengali)", "Bengali"],
  ["ਪੰਜਾਬੀ (Punjabi)", "Punjabi"],
  ["മലയാളം (Malayalam)", "Malayalam"],
  ["ଓଡ଼ିଆ (Odia)", "Odia"],
];

/**
 * Quick action cards shown on the Home screen.
 * ``target`` is the module key each card opens (see ``moduleCatalog``).
 */
export const quickActions = [
  {
    color: "bg-[#E8F3E9] text-[#287047]",
    icon: "crop",
    title: "Crop Advice",
    subtitle: "Best crops for your field",
    target: "crop-recommendation",
  },
  {
    color: "bg-[#E7F4F7] text-[#31768A]",
    icon: "droplet",
    title: "Watering Advice",
    subtitle: "Smart irrigation guidance",
    target: "irrigation",
  },
  {
    color: "bg-[#FFF3D9] text-[#A16912]",
    icon: "fertilizer",
    title: "Fertilizer Advice",
    subtitle: "Feed crops at the right time",
    target: "fertilizer",
  },
  {
    color: "bg-[#F2EAF8] text-[#76518D]",
    icon: "market",
    title: "Market Prices",
    subtitle: "Check nearby crop prices",
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
  { key: "home", label: "Home", icon: "home" },
  { key: "farm", label: "My Farm", icon: "farm" },
  { key: "advisor", label: "Advisor", icon: "bot" },
  { key: "insights", label: "Insights", icon: "chart" },
  { key: "more", label: "More", icon: "menu" },
];

/** Checklist items shown in the Farm Management add-farm form. */
export const farmChecklist = [
  "Crop management",
  "Growth stage",
  "Soil information",
  "Irrigation method",
  "Farm area & units",
  "GPS location",
];

/** Default reminder entries for the Farming Calendar module. */
export const defaultReminders = [
  {
    id: 1,
    title: "Irrigate tomato field",
    date: "Tomorrow • 6:30 AM",
    done: false,
  },
  {
    id: 2,
    title: "Apply second nitrogen dose",
    date: "24 October",
    done: false,
  },
  {
    id: 3,
    title: "Inspect onion for thrips",
    date: "Completed today",
    done: true,
  },
];

/**
 * Knowledge Center articles.
 * Each entry: [title, category, source].
 */
export const knowledgeArticles = [
  [
    "Managing tomato leaf curl",
    "Pests and diseases",
    "ICAR Extension Guide • 12 Sep 2025",
  ],
  [
    "Understanding soil pH",
    "Soil health",
    "Maharashtra Agriculture Dept • 2 Aug 2025",
  ],
  [
    "Efficient drip irrigation",
    "Irrigation",
    "Krishi Vigyan Kendra • 18 Jul 2025",
  ],
  [
    "PM-KISAN eligibility guide",
    "Agricultural schemes",
    "Government of India • 1 Oct 2025",
  ],
  [
    "Rabi season crop planning",
    "Seasonal farming guides",
    "ICAR • 28 Sep 2025",
  ],
];

/** Topic filter tags for the Knowledge Center search. */
export const knowledgeTopicTags = [
  "Crop management",
  "Soil health",
  "Fertilizers",
  "Irrigation",
  "Pests",
  "Weather",
];
