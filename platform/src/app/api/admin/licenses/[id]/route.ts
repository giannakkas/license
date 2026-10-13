import { prisma } from "@/lib/db";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/**
 * Change a licence. Form field `action`: update | lock | unlock | revoke | reinstate | delete.
 * `message` is what the programs show while locked / revoked.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const message = typeof body.message === "string" ? body.message.trim().slice(0, 300) : "";
  const license = await prisma.license.findUnique({ where: { id } });
  if (!license) return done(request, "/?error=Licence+not+found", { error: "not found" }, 404);
  const ip = clientIp(request);
  const back = `/licenses/${id}`;

  switch (action) {
    case "update": {
      const seats = Math.max(1, Math.min(500, Number.parseInt(String(body.maxSeats ?? license.maxSeats), 10) || license.maxSeats));
      const expiresRaw = typeof body.expiresAt === "string" ? body.expiresAt.trim() : "";
      const expiresAt = expiresRaw ? new Date(`${expiresRaw}T23:59:59Z`) : null;
      if (expiresAt && Number.isNaN(expiresAt.getTime())) return done(request, `${back}?error=Invalid+expiry+date`, { error: "invalid expiresAt" }, 400);
      await prisma.license.update({
        where: { id },
        data: {
          label: (typeof body.label === "string" && body.label.trim().slice(0, 120)) || license.label,
          notes: typeof body.notes === "string" ? body.notes.slice(0, 2000) : license.notes,
          maxSeats: seats,
          expiresAt,
        },
      });
      await prisma.event.create({ data: { kind: "updated", licenseId: id, detail: `seats ${seats}, expires ${expiresRaw || "never"}`, ip } });
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
      await prisma.event.create({ data: { kind: "deleted", detail: `licence ${license.key.slice(-5)} (${license.label}) deleted`, ip } });
      return done(request, "/");
    default:
      return done(request, `${back}?error=Unknown+action`, { error: "unknown action" }, 400);
  }
}
