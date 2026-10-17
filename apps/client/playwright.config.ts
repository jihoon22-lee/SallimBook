import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:18743", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "android-size", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 18743 --strictPort",
    url: "http://127.0.0.1:18743",
    reuseExistingServer: false,
  },
});
