import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig(base, {
  use: { ...base.use, baseURL: "http://127.0.0.1:18749" },
  webServer: { command: "pnpm exec vite --host 127.0.0.1 --port 18749 --strictPort", url: "http://127.0.0.1:18749", reuseExistingServer: false },
});
