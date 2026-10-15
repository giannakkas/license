import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { announceChange } from "@/lib/live";
import { fmtDay } from "@/lib/format";
import { addMonths, field, parseExpiry, parseSeats } from "@/lib/forms";
import { issueForSystem, normaliseMachineId, offlineFilesConfigured } from "@/lib/offline";
import { clientIp, done, publicOrigin, readBody, redirectTo, safePath, wantsJson } from "@/lib/request";

export const runtime = "nodejs";

/**
 * Change a licence. Form field `action`: update | extend | offline | lock | unlock | revoke | reinstate | delete.
 * `update` takes customerId, productId, label, maxSeats, expiresAt, notes; only the fields sent change.
 * `extend` takes months (1, 3, 6, 12) or until (YYYY-MM-DD) and an optional `back` path to return to.
 * `offline` issues a licence file: machineId (20 characters, from the program), hostname, expiresAt.
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
      announceChange();
      const changes = [`seats ${seats}`, `expires ${expires.date ? expires.date.toISOString().slice(0, 10) : "never"}`];
      if (customerId !== license.customerId) changes.push(`customer ${license.customer.name} → ${customer.name}`);
      if (productId !== license.productId) changes.push(`software ${license.product.name} → ${product.name}`);
      await prisma.event.create({ data: { kind: "updated", licenseId: id, detail: changes.join(", "), ip } });
      return done(request, back);
    }
    case "extend": {
      const months = Number.parseInt(String(body.months ?? ""), 10);
      const until = parseExpiry(body.until);
      let next: Date | null = null;
      if (until.ok && until.date) next = until.date;
      else if ([1, 3, 6, 12].includes(months)) {
        const base = license.expiresAt && license.expiresAt.getTime() > Date.now() ? license.expiresAt : new Date();
        next = addMonths(base, months);
      }
      if (!next) return fail("Choose how long to extend: 1, 3, 6 or 12 months, or a date");
      await prisma.license.update({ where: { id }, data: { expiresAt: next } });
      const offline = await prisma.system.updateMany({ where: { licenseId: id, mode: "offline" }, data: { offlineExpiresAt: next } });
      announceChange();
      await prisma.event.create({
        data: { kind: "extended", licenseId: id, detail: `expiry ${license.expiresAt ? fmtDay(license.expiresAt) : "never"} → ${fmtDay(next)}`, ip },
      });
      const notice =
        `Licence …${license.key.slice(-5)} (${license.customer.name}) extended to ${fmtDay(next)}.` +
        (offline.count ? ` ${offline.count} computer(s) with an offline file need a new file: download it from the licence page.` : "");
      const target = safePath(body.back, back);
      return done(request, `${target}${target.includes("?") ? "&" : "?"}notice=${encodeURIComponent(notice)}`, { ok: true, expiresAt: next.toISOString() });
    }
    case "offline": {
      if (!offlineFilesConfigured()) return fail("Offline licence files are not configured on this platform (LICENSE_FILE_PRIVATE_KEY)");
      const machineId = normaliseMachineId(body.machineId);
      if (!machineId) return fail("The computer id is 20 letters and digits, as shown on the program's activation screen");
      const hostname = field(body.hostname, 80) || null;
      const expires = parseExpiry(body.expiresAt);
      if (!expires.ok || !expires.date) return fail("An offline file needs an expiry date");
      if (expires.date.getTime() < Date.now()) return fail("The expiry date is in the past");
      if (license.status === "revoked") return fail("This licence is revoked; reinstate it first");
      let system = await prisma.system.findUnique({ where: { licenseId_machineId: { licenseId: id, machineId } } });
      if (!system) {
        const seats = await prisma.system.count({ where: { licenseId: id } });
        if (seats >= license.maxSeats) return fail(`All ${license.maxSeats} seat(s) of this licence are in use. Remove a computer or allow more computers first.`);
        system = await prisma.system.create({
          data: { licenseId: id, machineId, hostname, mode: "offline", offlineExpiresAt: expires.date, tokenHash: "pending" },
        });
      } else {
        system = await prisma.system.update({
          where: { id: system.id },
          data: { mode: "offline", offlineExpiresAt: expires.date, hostname: hostname ?? system.hostname, lastSeenAt: new Date() },
        });
        announceChange();
      }
      const file = await issueForSystem(license, system, process.env.PUBLIC_URL || publicOrigin(request));
      const who = hostname ?? machineId;
      await prisma.event.create({
        data: { kind: "file", licenseId: id, systemId: system.id, detail: `offline file issued for ${who}, valid until ${fmtDay(expires.date)}`, ip },
      });
      if (wantsJson(request)) {
        return NextResponse.json({ ok: true, systemId: system.id, filename: file.filename, content: file.content, expiresAt: expires.date.toISOString() }, { status: 201 });
      }
      const notice = `Offline file issued for ${who}, valid until ${fmtDay(expires.date)}. The download starts now; copy the file to that computer and use "Import licence file".`;
      return redirectTo(request, `${back}?notice=${encodeURIComponent(notice)}&download=${system.id}`);
    }
    case "lock":
      await prisma.license.update({ where: { id }, data: { status: "locked", lockMessage: message || null } });
      announceChange();
      await prisma.event.create({ data: { kind: "locked", licenseId: id, detail: `licence locked: ${message || "(no message)"}`, ip } });
      return done(request, back);
    case "unlock":
    case "reinstate":
      await prisma.license.update({ where: { id }, data: { status: "active", lockMessage: null } });
      announceChange();
      await prisma.event.create({ data: { kind: "unlocked", licenseId: id, detail: action === "reinstate" ? "licence reinstated" : "licence unlocked", ip } });
      return done(request, back);
    case "revoke":
      await prisma.license.update({ where: { id }, data: { status: "revoked", lockMessage: message || null } });
      announceChange();
      await prisma.event.create({ data: { kind: "revoked", licenseId: id, detail: `licence revoked: ${message || "(no message)"}`, ip } });
      return done(request, back);
    case "delete":
      await prisma.license.delete({ where: { id } });
      announceChange();
      await prisma.event.create({
        data: { kind: "deleted", detail: `licence …${license.key.slice(-5)} (${license.product.name}, ${license.customer.name}) deleted`, ip },
      });
      return done(request, `/customers/${license.customerId}`);
    default:
      return fail("Unknown action");
  }
}
