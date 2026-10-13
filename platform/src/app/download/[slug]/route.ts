import { prisma } from "@/lib/db";
import { fileDownload } from "@/lib/releases";

export const runtime = "nodejs";

/** Public: the latest build of a software, e.g. https://player.oncue.cy/download/monitoring-application */
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const product = await prisma.product.findUnique({ where: { slug }, include: { releases: { orderBy: { createdAt: "desc" }, take: 1 } } });
  const release = product?.releases[0];
  if (!release) return new Response("No download is available for this software.", { status: 404 });
  const response = await fileDownload(release.productId, release.id, release.filename);
  if (!response) return new Response("The build file is missing on the server.", { status: 404 });
  await prisma.release.update({ where: { id: release.id }, data: { downloads: { increment: 1 } } });
  return response;
}
