import { defineConfig } from "vitest/config";

// Day bucketing uses local time; the golden fixture was generated in UTC+8.
process.env.TZ = "Asia/Shanghai";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts"],
    environment: "node",
  },
});
