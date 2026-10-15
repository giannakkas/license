import { prisma } from "@/lib/db";
import { announceChange } from "@/lib/live";
import { clientIp, done, readBody, safePath } from "@/lib/request";

export const runtime = "nodejs";

/** Change one computer. Form field `action`: lock | unlock | remove. `message` shows on its lock screen. */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const message = typeof body.message === "string" ? body.message.trim().slice(0, 300) : "";
  const system = await prisma.system.findUnique({ where: { id } });
  if (!system) return done(request, "/?error=Computer+not+found", { error: "not found" }, 404);
  const ip = clientIp(request);
  const back = safePath(body.back, `/licenses/${system.licenseId}`);
  const who = system.hostname ?? system.machineId;

  switch (action) {
    case "lock":
      await prisma.system.update({ where: { id }, data: { status: "locked", lockMessage: message || null } });
      announceChange();
      await prisma.event.create({ data: { kind: "locked", licenseId: system.licenseId, systemId: id, detail: `${who} locked: ${message || "(no message)"}`, ip } });
      return done(request, back);
    case "unlock":
      await prisma.system.update({ where: { id }, data: { status: "active", lockMessage: null } });
      announceChange();
      await prisma.event.create({ data: { kind: "unlocked", licenseId: system.licenseId, systemId: id, detail: `${who} unlocked`, ip } });
      return done(request, back);
    case "remove":
      await prisma.system.delete({ where: { id } });
      announceChange();
      await prisma.event.create({ data: { kind: "removed", licenseId: system.licenseId, systemId: id, detail: `${who} removed (seat freed)`, ip } });
      return done(request, back);
    default:
      return done(request, `${back}?error=Unknown+action`, { error: "unknown action" }, 400);
  }
}
