import { defineConfig, devices } from "@playwright/test";

if (!process.env.SALLIMBOOK_HTTPS_ORIGIN || !process.env.SALLIMBOOK_HTTPS_FIXTURE || !process.env.SALLIMBOOK_HTTPS_SPKI || !process.env.SALLIMBOOK_HTTPS_OUTPUT) throw new Error("Run scripts/test_web_auth.py to provision the isolated HTTPS test.");

export default defineConfig({
  testDir: "./integration",
  testMatch: process.env.SALLIMBOOK_HTTPS_HOMECARE === "1" ? "homecare-https.spec.ts" : process.env.SALLIMBOOK_HTTPS_INSURANCE === "1" ? "insurance-https.spec.ts" : process.env.SALLIMBOOK_HTTPS_CASHFLOW === "1" ? "cashflow-https.spec.ts" : process.env.SALLIMBOOK_HTTPS_MONTHS === "1" ? "months-https.spec.ts" : process.env.SALLIMBOOK_HTTPS_FINANCE === "1" ? "finance-https.spec.ts" : process.env.SALLIMBOOK_HTTPS_PASSKEYS === "1" ? "passkeys-https.spec.ts" : "auth-https.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "dot",
  outputDir: process.env.SALLIMBOOK_HTTPS_OUTPUT,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN,
    trace: "off", screenshot: "off", video: "off",
    // Trust only this temporary certificate's public key in this test browser process.
    launchOptions: { args: [`--ignore-certificate-errors-spki-list=${process.env.SALLIMBOOK_HTTPS_SPKI}`, ...(process.env.SALLIMBOOK_HTTPS_PASSKEYS === "1" ? ["--host-resolver-rules=MAP sallimbook-passkey.test 127.0.0.1", "--no-proxy-server"] : [])] },
  },
});
