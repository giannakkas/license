import { SLUG_RE, slugify } from "@/lib/catalog";
import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Add a software. Fields: name (required), slug (optional, derived from the name), notes. */
export async function POST(request: Request) {
  const body = await readBody(request);
  const fail = (msg: string, status = 400) => done(request, `/products?error=${encodeURIComponent(msg)}`, { error: msg }, status);
  const name = field(body.name, 80);
  if (!name) return fail("A name is required");
  const slug = slugify(field(body.slug, 80) || name);
  if (!SLUG_RE.test(slug)) return fail("The slug needs at least two letters or digits (dashes allowed)");
  if (await prisma.product.findUnique({ where: { slug } })) return fail(`The slug "${slug}" is already used by another software`);
  const product = await prisma.product.create({ data: { name, slug, notes: field(body.notes, 2000) || null } });
  await prisma.event.create({ data: { kind: "software", detail: `${name} (${slug}) added`, ip: clientIp(request) } });
  return done(request, `/products/${product.id}`, { ok: true, id: product.id, slug }, 201);
}
