-- Offline licence files: a computer can hold a signed file instead of checking in.
ALTER TABLE "systems" ADD COLUMN "mode" TEXT NOT NULL DEFAULT 'online',
                      ADD COLUMN "offlineExpiresAt" TIMESTAMP(3);

-- Downloadable builds per software.
CREATE TABLE "releases" (
    "id" TEXT NOT NULL,
    "productId" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "filename" TEXT NOT NULL,
    "size" INTEGER NOT NULL,
    "sha256" TEXT NOT NULL,
    "notes" TEXT,
    "downloads" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "releases_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "releases_productId_createdAt_idx" ON "releases"("productId", "createdAt" DESC);

ALTER TABLE "releases" ADD CONSTRAINT "releases_productId_fkey" FOREIGN KEY ("productId") REFERENCES "products"("id") ON DELETE CASCADE ON UPDATE CASCADE;
