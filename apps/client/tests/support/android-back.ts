import type { Page } from "@playwright/test";

type Listener = (event: { canGoBack: boolean }) => void;
type Bridge = {
  PluginHeaders: { name: string; methods: { name: string; rtype: string }[] }[];
  nativeCallback: (
    plugin: string,
    method: string,
    args: Record<string, unknown>,
    listener: Listener,
  ) => string;
  nativePromise: (
    plugin: string,
    method: string,
    args?: Record<string, unknown>,
  ) => Promise<unknown>;
};

/** Add the Capacitor App plugin to an existing native mock; call after it is installed. */
export async function installAndroidBack(page: Page) {
  await page.addInitScript(() => {
    const capacitor = (window as unknown as { Capacitor: Bridge }).Capacitor;
    const callback = capacitor.nativeCallback;
    const promise = capacitor.nativePromise;
    capacitor.PluginHeaders.push({
      name: "App",
      methods: [
        { name: "addListener", rtype: "callback" },
        { name: "removeListener", rtype: "promise" },
        { name: "minimizeApp", rtype: "promise" },
      ],
    });
    const listeners = new Map<string, Listener>();
    let sequence = 0;
    Object.assign(window, {
      __androidBack: () => {
        for (const listener of [...listeners.values()]) listener({ canGoBack: true });
      },
    });
    capacitor.nativeCallback = (plugin, method, args, listener) => {
      if (plugin === "App" && args.eventName === "backButton") {
        const id = `synthetic-back-listener-${++sequence}`;
        listeners.set(id, listener);
        return id;
      }
      return callback(plugin, method, args, listener);
    };
    capacitor.nativePromise = (plugin, method, args) => {
      if (plugin !== "App") return promise(plugin, method, args);
      if (method === "removeListener") listeners.delete(String(args?.callbackId));
      return Promise.resolve();
    };
  });
  return {
    press: () =>
      page.evaluate(() => (window as unknown as { __androidBack: () => void }).__androidBack()),
  };
}
