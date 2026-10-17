import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";

/** Only history created by this router is eligible for in-app back navigation. */
export function canGoBackWithinApp(historyState: unknown): boolean {
  return typeof historyState === "object" && historyState !== null && "idx" in historyState
    && typeof historyState.idx === "number" && Number.isInteger(historyState.idx) && historyState.idx > 0;
}

/** Root back minimizes Android; a fresh deep link returns to its safe parent. */
export function registerAndroidBackHandler(onBack: () => boolean): () => void {
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") return () => {};
  let disposed = false;
  let removeListener: (() => Promise<void>) | undefined;
  const listener = App.addListener("backButton", () => {
    if (disposed) return;
    if (!onBack()) void App.minimizeApp().catch(() => {});
  });
  void listener.then((handle) => {
    if (disposed) void handle.remove().catch(() => {});
    else removeListener = () => handle.remove();
  }).catch(() => {});
  return () => {
    disposed = true;
    if (removeListener) void removeListener().catch(() => {});
  };
}
