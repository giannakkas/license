-- CreateTable
CREATE TABLE "licenses" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "product" TEXT NOT NULL DEFAULT 'monitoring-application',
    "label" TEXT NOT NULL,
    "notes" TEXT,
    "status" TEXT NOT NULL DEFAULT 'active',
    "lockMessage" TEXT,
    "maxSeats" INTEGER NOT NULL DEFAULT 1,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "licenses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "systems" (
    "id" TEXT NOT NULL,
    "licenseId" TEXT NOT NULL,
    "machineId" TEXT NOT NULL,
    "hostname" TEXT,
    "os" TEXT,
    "appVersion" TEXT,
    "ip" TEXT,
    "status" TEXT NOT NULL DEFAULT 'active',
    "lockMessage" TEXT,
    "tokenHash" TEXT NOT NULL,
    "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "systems_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "events" (
    "id" TEXT NOT NULL,
    "licenseId" TEXT,
    "systemId" TEXT,
    "kind" TEXT NOT NULL,
    "detail" TEXT,
    "ip" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "events_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "licenses_key_key" ON "licenses"("key");
CREATE INDEX "licenses_status_idx" ON "licenses"("status");
CREATE UNIQUE INDEX "systems_licenseId_machineId_key" ON "systems"("licenseId", "machineId");
CREATE INDEX "systems_lastSeenAt_idx" ON "systems"("lastSeenAt" DESC);
CREATE INDEX "events_createdAt_idx" ON "events"("createdAt" DESC);
CREATE INDEX "events_licenseId_createdAt_idx" ON "events"("licenseId", "createdAt" DESC);

-- AddForeignKey
ALTER TABLE "systems" ADD CONSTRAINT "systems_licenseId_fkey" FOREIGN KEY ("licenseId") REFERENCES "licenses"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "events" ADD CONSTRAINT "events_licenseId_fkey" FOREIGN KEY ("licenseId") REFERENCES "licenses"("id") ON DELETE SET NULL ON UPDATE CASCADE;
