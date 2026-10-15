import { SLUG_RE, VERSION_RE, slugify } from "@/lib/catalog";
import { prisma } from "@/lib/db";
import { announceChange } from "@/lib/live";
import { field } from "@/lib/forms";
import { removeFile } from "@/lib/releases";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Change a software. Form field `action`: update (name, slug, notes, minVersion) | delete (with its licences, computers and builds). */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const action = typeof body.action === "string" ? body.action : "";
  const product = await prisma.product.findUnique({
    where: { id },
    include: { _count: { select: { licenses: true } }, releases: { select: { id: true, filename: true } } },
  });
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
      const minVersion = "minVersion" in body ? field(body.minVersion, 40) || null : product.minVersion;
      if (minVersion && !VERSION_RE.test(minVersion)) return fail("A minimum version looks like 1.4.0 (or leave it empty)");
      await prisma.product.update({
        where: { id },
        data: { name, slug, minVersion, notes: "notes" in body ? field(body.notes, 2000) || null : product.notes },
      });
      const minNote = minVersion !== product.minVersion ? `, minimum version ${minVersion ?? "none"}` : "";
      await prisma.event.create({ data: { kind: "software", detail: `${name} (${slug}) updated${minNote}`, ip } });
      return done(request, back);
    }
    case "delete": {
      const computers = await prisma.system.count({ where: { license: { productId: id } } });
      for (const r of product.releases) await removeFile(id, r.id, r.filename);
      await prisma.product.delete({ where: { id } });
      announceChange();
      await prisma.event.create({
        data: {
          kind: "software",
          detail: `${product.name} (${product.slug}) deleted with ${product._count.licenses} licence(s), ${computers} computer(s) and ${product.releases.length} build(s)`,
          ip,
        },
      });
      return done(request, "/products");
    }
    default:
      return fail("Unknown action");
  }
}
