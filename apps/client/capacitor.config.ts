import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "io.github.jihoon22lee.sallimbook",
  appName: "SallimBook",
  webDir: "dist",
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false },
};

export default config;
