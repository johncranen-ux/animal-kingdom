import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    // Page origin is the API base (see js/app.js), so match the backend URL tests assert on
    environmentOptions: { jsdom: { url: "http://localhost:8000" } },
    globals: true,
    passWithNoTests: true,
  },
});
