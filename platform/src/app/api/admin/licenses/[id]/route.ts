import { prisma } from "@/lib/db";
import { field, parseExpiry, parseSeats } from "@/lib/forms";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/**
 * Change a licence. Form field `action`: update | lock | unlock | revoke | reinstate | delete.
 * `update` takes customerId, productId, label, maxSeats, expiresAt, notes; only the fields sent change.
 * `message` is what the programs show while locked / revoked.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const message = field(body.message, 300);
  const license = await prisma.license.findUnique({ where: { id }, include: { customer: true, product: true } });
  if (!license) return done(request, "/?error=Licence+not+found", { error: "not found" }, 404);
  const ip = clientIp(request);
  const back = `/licenses/${id}`;
  const fail = (msg: string, status = 400) => done(request, `${back}?error=${encodeURIComponent(msg)}`, { error: msg }, status);

  switch (action) {
    case "update": {
      const seats = "maxSeats" in body ? parseSeats(body.maxSeats, license.maxSeats) : license.maxSeats;
      const expires = "expiresAt" in body ? parseExpiry(body.expiresAt) : { ok: true as const, date: license.expiresAt };
      if (!expires.ok) return fail("Invalid expiry date");
      const customerId = field(body.customerId, 64) || license.customerId;
      const productId = field(body.productId, 64) || license.productId;
      const [customer, product] = await Promise.all([
        prisma.customer.findUnique({ where: { id: customerId } }),
        prisma.product.findUnique({ where: { id: productId } }),
      ]);
      if (!customer) return fail("Customer not found");
      if (!product) return fail("Software not found");
      await prisma.license.update({
        where: { id },
        data: {
          customerId,
          productId,
          label: "label" in body ? field(body.label, 120) || null : license.label,
          notes: "notes" in body ? field(body.notes, 2000) || null : license.notes,
          maxSeats: seats,
          expiresAt: expires.date,
        },
      });
      const changes = [`seats ${seats}`, `expires ${expires.date ? expires.date.toISOString().slice(0, 10) : "never"}`];
      if (customerId !== license.customerId) changes.push(`customer ${license.customer.name} → ${customer.name}`);
      if (productId !== license.productId) changes.push(`software ${license.product.name} → ${product.name}`);
      await prisma.event.create({ data: { kind: "updated", licenseId: id, detail: changes.join(", "), ip } });
      return done(request, back);
    }
    case "lock":
      await prisma.license.update({ where: { id }, data: { status: "locked", lockMessage: message || null } });
      await prisma.event.create({ data: { kind: "locked", licenseId: id, detail: `licence locked: ${message || "(no message)"}`, ip } });
      return done(request, back);
    case "unlock":
    case "reinstate":
      await prisma.license.update({ where: { id }, data: { status: "active", lockMessage: null } });
      await prisma.event.create({ data: { kind: "unlocked", licenseId: id, detail: action === "reinstate" ? "licence reinstated" : "licence unlocked", ip } });
      return done(request, back);
    case "revoke":
      await prisma.license.update({ where: { id }, data: { status: "revoked", lockMessage: message || null } });
      await prisma.event.create({ data: { kind: "revoked", licenseId: id, detail: `licence revoked: ${message || "(no message)"}`, ip } });
      return done(request, back);
    case "delete":
      await prisma.license.delete({ where: { id } });
      await prisma.event.create({
        data: { kind: "deleted", detail: `licence …${license.key.slice(-5)} (${license.product.name}, ${license.customer.name}) deleted`, ip },
      });
      return done(request, `/customers/${license.customerId}`);
    default:
      return fail("Unknown action");
  }
}
