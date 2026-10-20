import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
// Spread the base once: merging two configs would start both webServer entries.
export default defineConfig({
  ...base,
  use: { ...base.use, baseURL: "http://127.0.0.1:18750" },
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 18750 --strictPort",
    url: "http://127.0.0.1:18750",
    reuseExistingServer: false,
  },
});
