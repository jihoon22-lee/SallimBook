import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";

const observers = new Set<() => void>();
let stop: (() => void) | undefined;

/** One platform listener serves all mounted readers, including Android activity resumes. */
export function observeAppResume(observer: () => void): () => void {
  observers.add(observer);
  if (!stop) {
    const notify = () => {
      if (document.visibilityState === "hidden") return;
      for (const callback of observers) callback();
    };
    window.addEventListener("focus", notify);
    document.addEventListener("visibilitychange", notify);
    const native = Capacitor.isNativePlatform()
      ? App.addListener("appStateChange", ({ isActive }) => {
          if (isActive) notify();
        }).catch(() => null)
      : null;
    stop = () => {
      window.removeEventListener("focus", notify);
      document.removeEventListener("visibilitychange", notify);
      if (native) void native.then((handle) => handle?.remove()).catch(() => {});
    };
  }
  return () => {
    observers.delete(observer);
    if (!observers.size) {
      stop?.();
      stop = undefined;
    }
  };
}
