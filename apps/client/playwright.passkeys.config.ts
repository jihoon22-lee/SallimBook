import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// A dedicated port permits SB-006 validation beside the main checkout's 18743 suite.
export default defineConfig(base, {
  use: { ...base.use, baseURL: "http://127.0.0.1:18747" },
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 18747 --strictPort",
    url: "http://127.0.0.1:18747",
    reuseExistingServer: false,
  },
});
