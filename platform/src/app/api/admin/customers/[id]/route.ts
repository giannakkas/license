import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Change a customer. Form field `action`: update (name, email, phone, notes) | delete (only without licences). */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const customer = await prisma.customer.findUnique({ where: { id }, include: { _count: { select: { licenses: true } } } });
  if (!customer) return done(request, "/customers?error=Customer+not+found", { error: "not found" }, 404);
  const ip = clientIp(request);
  const back = `/customers/${id}`;
  const fail = (msg: string, status = 400) => done(request, `${back}?error=${encodeURIComponent(msg)}`, { error: msg }, status);

  switch (action) {
    case "update": {
      const name = field(body.name, 120) || customer.name;
      await prisma.customer.update({
        where: { id },
        data: {
          name,
          email: "email" in body ? field(body.email, 120) || null : customer.email,
          phone: "phone" in body ? field(body.phone, 60) || null : customer.phone,
          notes: "notes" in body ? field(body.notes, 2000) || null : customer.notes,
        },
      });
      await prisma.event.create({ data: { kind: "customer", detail: `${name} updated`, ip } });
      return done(request, back);
    }
    case "delete":
      if (customer._count.licenses > 0) return fail(`${customer.name} still has ${customer._count.licenses} licence(s). Delete or move them first.`);
      await prisma.customer.delete({ where: { id } });
      await prisma.event.create({ data: { kind: "customer", detail: `${customer.name} deleted`, ip } });
      return done(request, "/customers");
    default:
      return fail("Unknown action");
  }
}
