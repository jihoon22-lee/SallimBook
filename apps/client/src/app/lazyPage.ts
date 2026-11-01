import { lazy, type ComponentType } from "react";

const reloadKey = "sallimbook:stale-chunk-reload";

/** The entry script's hashed file name tells one deployed build from the next. */
function build() {
  return document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src ?? "";
}

/** Reload at most once per build, so a file missing from the current build cannot loop. */
function reloadForNewBuild() {
  try {
    if (sessionStorage.getItem(reloadKey) === build()) return false;
    sessionStorage.setItem(reloadKey, build());
  } catch {
    return false; // Without storage a reload could repeat; show the error screen instead.
  }
  location.reload();
  return true;
}

/**
 * A screen fetched on its first visit. After an update the previous build's file names no
 * longer exist, so one reload brings the current build; offline it stays an error, which
 * the error screen offers to retry.
 */
export function lazyPage<P extends object>(load: () => Promise<ComponentType<P>>) {
  return lazy(async () => {
    try {
      return { default: await load() };
    } catch (error) {
      if (navigator.onLine && reloadForNewBuild()) return new Promise<never>(() => {});
      throw error;
    }
  });
}
