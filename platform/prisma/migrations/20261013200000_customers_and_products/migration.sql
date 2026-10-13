-- Customers and softwares (products) become their own tables. Existing licences are re-linked:
-- one product per slug already in use, one customer per distinct "licensed to" label.

-- CreateTable
CREATE TABLE "products" (
    "id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "products_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "customers" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "email" TEXT,
    "phone" TEXT,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "customers_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "products_slug_key" ON "products"("slug");
CREATE INDEX "customers_name_idx" ON "customers"("name");

-- AlterTable: new links, label becomes an optional reference
ALTER TABLE "licenses" ADD COLUMN "productId" TEXT, ADD COLUMN "customerId" TEXT;
ALTER TABLE "licenses" ALTER COLUMN "label" DROP NOT NULL;

-- Backfill: a product for every slug in use (the Monitoring Application always exists)
INSERT INTO "products" ("id", "slug", "name", "updatedAt")
SELECT replace(gen_random_uuid()::text, '-', ''), s.slug,
       CASE WHEN s.slug = 'monitoring-application' THEN 'Monitoring Application' ELSE s.slug END,
       CURRENT_TIMESTAMP
FROM (SELECT DISTINCT "product" AS slug FROM "licenses" UNION SELECT 'monitoring-application') s;

UPDATE "licenses" l SET "productId" = p."id" FROM "products" p WHERE p."slug" = l."product";

-- Backfill: a customer per distinct "licensed to" text; the text moves to the customer
INSERT INTO "customers" ("id", "name", "updatedAt")
SELECT replace(gen_random_uuid()::text, '-', ''), s.name, CURRENT_TIMESTAMP
FROM (SELECT DISTINCT "label" AS name FROM "licenses") s;

UPDATE "licenses" l SET "customerId" = c."id", "label" = NULL FROM "customers" c WHERE c."name" = l."label";

-- Make the links mandatory and drop the old text column
ALTER TABLE "licenses" ALTER COLUMN "productId" SET NOT NULL, ALTER COLUMN "customerId" SET NOT NULL;
ALTER TABLE "licenses" DROP COLUMN "product";

-- CreateIndex
CREATE INDEX "licenses_productId_idx" ON "licenses"("productId");
CREATE INDEX "licenses_customerId_idx" ON "licenses"("customerId");

-- AddForeignKey
ALTER TABLE "licenses" ADD CONSTRAINT "licenses_productId_fkey" FOREIGN KEY ("productId") REFERENCES "products"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "licenses" ADD CONSTRAINT "licenses_customerId_fkey" FOREIGN KEY ("customerId") REFERENCES "customers"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
