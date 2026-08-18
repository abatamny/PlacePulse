import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "line",
  timeout: 30_000,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.PLACEPULSE_E2E_BASE_URL ?? "http://localhost",
    ignoreHTTPSErrors: true,
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
});
