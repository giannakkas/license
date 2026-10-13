import { prisma } from "@/lib/db";
import { generateKey } from "@/lib/keys";
import { DEFAULT_PRODUCT } from "@/lib/licensing";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Create a licence. Form fields: label, product, maxSeats, expiresAt (YYYY-MM-DD), notes. */
export async function POST(request: Request) {
  const body = await readBody(request);
  const label = typeof body.label === "string" ? body.label.trim().slice(0, 120) : "";
  if (!label) return done(request, "/?error=A+label+is+required", { error: "label is required" }, 400);
  const seats = Math.max(1, Math.min(500, Number.parseInt(String(body.maxSeats ?? "1"), 10) || 1));
  const expiresRaw = typeof body.expiresAt === "string" ? body.expiresAt.trim() : "";
  const expiresAt = expiresRaw ? new Date(`${expiresRaw}T23:59:59Z`) : null;
  if (expiresAt && Number.isNaN(expiresAt.getTime())) {
    return done(request, "/?error=Invalid+expiry+date", { error: "invalid expiresAt" }, 400);
  }
  const license = await prisma.license.create({
    data: {
      key: generateKey(),
      label,
      product: (typeof body.product === "string" && body.product.trim()) || DEFAULT_PRODUCT,
      maxSeats: seats,
      expiresAt,
      notes: typeof body.notes === "string" ? body.notes.slice(0, 2000) : null,
    },
  });
  await prisma.event.create({ data: { kind: "created", licenseId: license.id, detail: `${label}, ${seats} seat(s)`, ip: clientIp(request) } });
  return done(request, `/licenses/${license.id}`, { ok: true, id: license.id, key: license.key }, 201);
}
