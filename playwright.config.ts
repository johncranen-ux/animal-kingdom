import { defineConfig, devices } from '@playwright/test';
import path from 'path';

const PORT = process.env.AK_PORT ?? '8000';
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,   // chat tests share Ollama — run sequentially
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    headless: true,
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      // Backend also serves the frontend (same origin, no build step needed).
      // Same event loop as manage.py: the default one can lose its listener on Windows.
      command: path.join('..', '.venv', 'Scripts', 'python.exe') + ` -m uvicorn app.main:app --port ${PORT} --loop asyncio:SelectorEventLoop`,
      cwd: path.join(process.cwd(), 'backend'),
      url: `${BASE_URL}/health`,
      reuseExistingServer: true,
      timeout: 20_000,
    },
  ],
});
