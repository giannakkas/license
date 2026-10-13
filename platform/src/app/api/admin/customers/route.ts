import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Add a customer. Fields: name (required), email, phone, notes. */
export async function POST(request: Request) {
  const body = await readBody(request);
  const name = field(body.name, 120);
  if (!name) return done(request, "/customers?error=A+name+is+required", { error: "name is required" }, 400);
  const customer = await prisma.customer.create({
    data: { name, email: field(body.email, 120) || null, phone: field(body.phone, 60) || null, notes: field(body.notes, 2000) || null },
  });
  await prisma.event.create({ data: { kind: "customer", detail: `${name} added`, ip: clientIp(request) } });
  return done(request, `/customers/${customer.id}`, { ok: true, id: customer.id }, 201);
}
