/**
 * The attributes the stylesheets key off, set before the first paint.
 *
 * Ported from the inline script at the top of base.html. It has to run before
 * anything is drawn: the theme would otherwise flash light before turning dark,
 * and - the reason it was written this way - a private project's plan would be
 * on screen for a frame before safe mode covers it.
 */

export type Appearance = {
  ui: string;
  theme: string;
  projectLayout: string;
  planEditor: string;
  safeMode: "on" | "off";
};

const FALLBACK: Appearance = {
  ui: "modern",
  theme: "light",
  projectLayout: "sidebar",
  planEditor: "blocks",
  safeMode: "off",
};

export function readAppearance(): Appearance {
  try {
    const ui = localStorage.getItem("app-ui") || "modern";
    const stored = localStorage.getItem("app-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;

    return {
      ui,
      // The classic skin is light-only, like the original UI.
      theme: ui === "classic" ? "light" : stored || (prefersDark ? "dark" : "light"),
      projectLayout: localStorage.getItem("app-project-layout") || "sidebar",
      planEditor: localStorage.getItem("app-plan-editor") || "blocks",
      safeMode: localStorage.getItem("app-safe-mode") === "on" ? "on" : "off",
    };
  } catch {
    return FALLBACK;
  }
}

export function applyAppearance(appearance: Appearance = readAppearance()): void {
  const root = document.documentElement;
  root.setAttribute("data-ui", appearance.ui);
  root.setAttribute("data-bs-theme", appearance.theme);
  root.setAttribute("data-project-layout", appearance.projectLayout);
  root.setAttribute("data-plan-editor", appearance.planEditor);
  root.setAttribute("data-safe-mode", appearance.safeMode);
}

/** Flip light and dark, and remember it. */
export function toggleTheme(): string {
  const next = document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
  try {
    localStorage.setItem("app-theme", next);
  } catch {
    // A browser refusing storage still gets the change for this page.
  }
  document.documentElement.setAttribute("data-bs-theme", next);
  return next;
}

/**
 * Safe mode: a curtain over a private project's plan and thoughts.
 *
 * Still browser-side only, as ARCHITECTURE.md insists - the difference now is
 * that the text it covers really is on this device rather than sent by a server.
 */
export function toggleSafeMode(): "on" | "off" {
  const next = document.documentElement.getAttribute("data-safe-mode") === "on" ? "off" : "on";
  try {
    localStorage.setItem("app-safe-mode", next);
  } catch {
    // As above.
  }
  document.documentElement.setAttribute("data-safe-mode", next);
  window.dispatchEvent(new CustomEvent("safe-mode-change", { detail: next }));
  return next;
}
