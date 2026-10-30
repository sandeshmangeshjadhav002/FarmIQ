import { describe, it, expect } from "vitest";
import {
  ADMIN_ROLE,
  browsableModules,
  canAccessAdminTools,
  moduleByKey,
  moduleCatalog,
  navKeyForSection,
  sectionByKey,
  sections,
} from "./modules";

const FARMER = { role: "farmer" };
const EXPERT = { role: ADMIN_ROLE };

describe("six-section model", () => {
  it("exposes exactly the six consolidated sections, in order", () => {
    expect(sections.map((s) => s.key)).toEqual([
      "home",
      "farm",
      "advisor",
      "insights",
      "knowledge",
      "admin",
    ]);
  });

  it("assigns every module in the catalogue to a known section", () => {
    for (const item of moduleCatalog) {
      expect(sectionByKey(item.section), `${item.key} → ${item.section}`).toBeTruthy();
    }
  });

  it("has no duplicate module keys", () => {
    const keys = moduleCatalog.map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("navKeyForSection", () => {
  it("maps each section onto the tab that owns it", () => {
    expect(navKeyForSection("farm")).toBe("farm");
    expect(navKeyForSection("advisor")).toBe("advisor");
    expect(navKeyForSection("insights")).toBe("insights");
  });

  it("routes the Knowledge and Admin sections through the More tab", () => {
    expect(navKeyForSection("knowledge")).toBe("more");
    expect(navKeyForSection("admin")).toBe("more");
  });

  it("falls back to Home for an unknown section so a tab is always lit", () => {
    expect(navKeyForSection(undefined)).toBe("home");
    expect(navKeyForSection("nope")).toBe("home");
  });
});

describe("admin gate", () => {
  it("authorises only the advisory role", () => {
    expect(canAccessAdminTools(EXPERT)).toBe(true);
    expect(canAccessAdminTools(FARMER)).toBe(false);
    expect(canAccessAdminTools(null)).toBe(false);
    expect(canAccessAdminTools(undefined)).toBe(false);
  });
});

describe("browsableModules", () => {
  const keys = (user, opts) => browsableModules(user, opts).map((m) => m.key);

  it("hides contextual tools from the browse grid", () => {
    const visible = keys(FARMER);
    expect(visible).not.toContain("devices");
    expect(visible).not.toContain("sensor-simulator");
  });

  it("still returns contextual tools when they are explicitly requested", () => {
    const visible = keys(FARMER, { includeContextual: true });
    expect(visible).toContain("devices");
    expect(visible).toContain("sensor-simulator");
  });

  it("hides the administrative tools from a farmer", () => {
    const visible = keys(FARMER);
    expect(visible).not.toContain("mlops");
    expect(visible).not.toContain("admin");
    expect(visible).not.toContain("hackathon-demo");
  });

  it("shows the administrative tools to an authorised expert", () => {
    const visible = keys(EXPERT);
    expect(visible).toContain("mlops");
    expect(visible).toContain("admin");
  });

  it("keeps the farmer-facing tools for both roles", () => {
    for (const visible of [keys(FARMER), keys(EXPERT)]) {
      expect(visible).toContain("farm-management");
      expect(visible).toContain("crop-recommendation");
      expect(visible).toContain("yield");
      expect(visible).toContain("knowledge");
    }
  });
});

describe("moduleByKey", () => {
  it("resolves a key and returns undefined for an unknown one", () => {
    expect(moduleByKey("irrigation")?.title).toBe("Smart Irrigation");
    expect(moduleByKey("does-not-exist")).toBeUndefined();
  });
});
