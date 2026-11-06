/**
 * The colour mode the page is showing right now, for components that need
 * hex values rather than CSS variables (Plot charts).
 *
 * Same rule as the generated theme CSS (themes.ts): <html data-mode> wins,
 * otherwise the OS setting. Re-renders when either changes.
 */

import { useSyncExternalStore } from "react";

import type { Mode } from "../../theme/themes";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function currentMode(): Mode {
  const chosen = document.documentElement.dataset.mode;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);

  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-mode"] });

  return () => {
    media.removeEventListener("change", onChange);
    observer.disconnect();
  };
}

/** "light" on the server; charts don't render there anyway. */
export function useMode(): Mode {
  return useSyncExternalStore(subscribe, currentMode, () => "light");
}
