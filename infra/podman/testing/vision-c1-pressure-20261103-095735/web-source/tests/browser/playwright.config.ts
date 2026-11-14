import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  reporter: 'list',
  outputDir: '/workspace/playwright-artifacts',
  use: {
    baseURL: process.env.BASE_URL || process.env.TEST_WEB_BASE_URL || 'http://127.0.0.1:3000',
    browserName: 'chromium',
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
  },
})
