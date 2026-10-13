import { SLUG_RE, slugify } from "@/lib/catalog";
import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Change a software. Form field `action`: update (name, slug, notes) | delete (only without licences). */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const product = await prisma.product.findUnique({ where: { id }, include: { _count: { select: { licenses: true } } } });
  if (!product) return done(request, "/products?error=Software+not+found", { error: "not found" }, 404);
  const ip = clientIp(request);
  const back = `/products/${id}`;
  const fail = (msg: string, status = 400) => done(request, `${back}?error=${encodeURIComponent(msg)}`, { error: msg }, status);

  switch (action) {
    case "update": {
      const name = field(body.name, 80) || product.name;
      const slug = "slug" in body ? slugify(field(body.slug, 80) || name) : product.slug;
      if (!SLUG_RE.test(slug)) return fail("The slug needs at least two letters or digits (dashes allowed)");
      if (slug !== product.slug && (await prisma.product.findUnique({ where: { slug } }))) return fail(`The slug "${slug}" is already used by another software`);
      await prisma.product.update({
        where: { id },
        data: { name, slug, notes: "notes" in body ? field(body.notes, 2000) || null : product.notes },
      });
      await prisma.event.create({ data: { kind: "software", detail: `${name} (${slug}) updated`, ip } });
      return done(request, back);
    }
    case "delete":
      if (product._count.licenses > 0) return fail(`${product.name} still has ${product._count.licenses} licence(s). Delete or move them first.`);
      await prisma.product.delete({ where: { id } });
      await prisma.event.create({ data: { kind: "software", detail: `${product.name} (${product.slug}) deleted`, ip } });
      return done(request, "/products");
    default:
      return fail("Unknown action");
  }
}
