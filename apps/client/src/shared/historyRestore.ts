import { useEffect, useLayoutEffect, useRef } from "react";
import type { NavigationType } from "react-router";

// Per-history-entry numbers (scroll offset, loaded page count) live only in this page's
// memory: the app keeps nothing in browser storage, so a full reload starts at the top.
const KEEP = 50;
const RESTORE_LIMIT_MS = 3000;
const USER_INPUT = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

type HistoryLocation = { key: string; pathname: string; search?: string };

const saved = { scroll: new Map<string, number>(), pages: new Map<string, number>() };

function put(map: Map<string, number>, key: string, value: number) {
  map.delete(key);
  map.set(key, Math.max(0, Math.round(value)));
  for (const old of map.keys()) {
    if (map.size <= KEEP) break;
    map.delete(old);
  }
}

/** The first entry of a page load has no router key; tell such entries apart by URL. */
export function historyEntryKey(location: HistoryLocation): string {
  return location.key === "default"
    ? `default:${location.pathname}${location.search ?? ""}`
    : location.key;
}

export function rememberListPages(entryKey: string, list: string, pages: number): void {
  put(saved.pages, `${entryKey}:${list}`, pages);
}

export function rememberedListPages(entryKey: string, list: string): number {
  return saved.pages.get(`${entryKey}:${list}`) ?? 1;
}

/** Remember each history entry's scroll offset and bring it back on POP, even for late lists. */
export function useHistoryScroll(location: HistoryLocation, navigationType: NavigationType): void {
  const entry = historyEntryKey(location);
  const previousPath = useRef(location.pathname);
  const latest = useRef({ navigationType, pathname: location.pathname });
  latest.current = { navigationType, pathname: location.pathname };

  useEffect(() => {
    if (!("scrollRestoration" in history)) return;
    const before = history.scrollRestoration;
    history.scrollRestoration = "manual";
    return () => {
      history.scrollRestoration = before;
    };
  }, []);

  // A layout effect detaches before the next screen paints, so the clamped offset of a
  // shorter screen is never written to the entry being left.
  useLayoutEffect(() => {
    let frame = 0;
    let offset = window.scrollY;
    const record = () => put(saved.scroll, entry, offset);
    const onScroll = () => {
      offset = window.scrollY;
      if (!frame)
        frame = requestAnimationFrame(() => {
          frame = 0;
          record();
        });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) {
        cancelAnimationFrame(frame);
        record();
      }
    };
  }, [entry]);

  useEffect(() => {
    const { navigationType: type, pathname } = latest.current;
    const pathChanged = previousPath.current !== pathname;
    previousPath.current = pathname;
    if (type !== "POP") {
      if (pathChanged) window.scrollTo(0, 0);
      return;
    }
    const target = saved.scroll.get(entry) ?? 0;
    const reach = () => {
      window.scrollTo(0, target);
      return Math.abs(window.scrollY - target) <= 2;
    };
    if (reach()) return;
    const observer = new ResizeObserver(() => {
      if (reach()) stop();
    });
    const timer = window.setTimeout(() => stop(), RESTORE_LIMIT_MS);
    function stop() {
      observer.disconnect();
      window.clearTimeout(timer);
      for (const type of USER_INPUT) window.removeEventListener(type, stop);
    }
    observer.observe(document.body);
    for (const type of USER_INPUT) window.addEventListener(type, stop, { passive: true });
    return stop;
  }, [entry]);
}
