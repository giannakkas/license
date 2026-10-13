-- Deleting a software or a customer now deletes its licences (and, through them, their computers).
ALTER TABLE "licenses" DROP CONSTRAINT "licenses_productId_fkey";
ALTER TABLE "licenses" ADD CONSTRAINT "licenses_productId_fkey" FOREIGN KEY ("productId") REFERENCES "products"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "licenses" DROP CONSTRAINT "licenses_customerId_fkey";
ALTER TABLE "licenses" ADD CONSTRAINT "licenses_customerId_fkey" FOREIGN KEY ("customerId") REFERENCES "customers"("id") ON DELETE CASCADE ON UPDATE CASCADE;
