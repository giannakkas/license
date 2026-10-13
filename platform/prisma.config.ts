import { defineConfig } from "prisma/config";

// Node 20.12+ can read .env without a dependency; Next.js loads it for the app
// itself, but the Prisma CLI runs outside Next.
try {
  process.loadEnvFile(".env");
} catch {
  // No .env file (e.g. on Railway, where vars come from the platform).
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations",
  },
  datasource: {
    url: process.env["DATABASE_URL"],
  },
});
