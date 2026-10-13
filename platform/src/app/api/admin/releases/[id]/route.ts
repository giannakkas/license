import { prisma } from "@/lib/db";
import { removeFile } from "@/lib/releases";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Change a build. Form field `action`: delete. */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await readBody(request);
  const release = await prisma.release.findUnique({ where: { id }, include: { product: { select: { name: true } } } });
  if (!release) return done(request, "/products?error=Build+not+found", { error: "not found" }, 404);
  const back = `/products/${release.productId}`;
  if (body.action !== "delete") return done(request, `${back}?error=Unknown+action`, { error: "unknown action" }, 400);
  await removeFile(release.productId, release.id, release.filename);
  await prisma.release.delete({ where: { id } });
  await prisma.event.create({ data: { kind: "release", detail: `${release.product.name} ${release.version} deleted`, ip: clientIp(request) } });
  return done(request, back);
}
