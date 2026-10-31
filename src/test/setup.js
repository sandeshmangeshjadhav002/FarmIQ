// Global test setup: initialises i18n, adds jest-dom matchers and clears
// localStorage between tests.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

import i18n from "@/i18n";

// Newer Node runtimes expose an experimental `localStorage` global that shadows
// jsdom's implementation and reads as `undefined` unless the process was started
// with --localstorage-file. Because that global already exists, jsdom never gets
// to replace it, so `localStorage.clear()` in the hooks below blows up.
//
// Re-point both `globalThis` and `window` at a working Storage: jsdom's when it
// is actually usable, otherwise a minimal in-memory stand-in.
function installLocalStorage() {
  const candidates = [];
  try {
    candidates.push(globalThis.localStorage);
  } catch {
    /* experimental getter throws when unconfigured */
  }
  try {
    candidates.push(window.localStorage);
  } catch {
    /* opaque origin */
  }

  const usable =
    candidates.find((s) => s && typeof s.clear === "function") ??
    createMemoryStorage();

  for (const target of [globalThis, typeof window === "undefined" ? null : window]) {
    if (!target) continue;
    try {
      Object.defineProperty(target, "localStorage", {
        value: usable,
        configurable: true,
        writable: true,
      });
    } catch {
      /* non-configurable global — the fallback below still covers the app */
    }
  }
}

function createMemoryStorage() {
  const store = new Map();
  return {
    get length() {
      return store.size;
    },
    key: (index) => Array.from(store.keys())[index] ?? null,
    getItem: (key) => (store.has(String(key)) ? store.get(String(key)) : null),
    setItem: (key, value) => {
      store.set(String(key), String(value));
    },
    removeItem: (key) => {
      store.delete(String(key));
    },
    clear: () => {
      store.clear();
    },
  };
}

installLocalStorage();

// Components call `useTranslation()`, which needs an initialised instance.
// Keeping every test in English makes the assertions below deterministic even
// after a test switches language.
beforeEach(() => {
  i18n.changeLanguage("en");
});

afterEach(() => {
  cleanup();
  globalThis.localStorage?.clear?.();
});
