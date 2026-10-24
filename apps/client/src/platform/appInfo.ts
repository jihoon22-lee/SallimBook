import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
export async function installedAppInfo(): Promise<{ version: string; build: string } | null> {
  if (!Capacitor.isNativePlatform()) return null;
  const info = await App.getInfo();
  return { version: info.version, build: info.build };
}
