import { prisma } from "@/lib/db";
import { fileDownload } from "@/lib/releases";

export const runtime = "nodejs";

/** Public: one specific build of a software by release id. */
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string; release: string }> }) {
  const { slug, release: releaseId } = await params;
  const release = await prisma.release.findFirst({ where: { id: releaseId, product: { slug } } });
  if (!release) return new Response("No such build.", { status: 404 });
  const response = await fileDownload(release.productId, release.id, release.filename);
  if (!response) return new Response("The build file is missing on the server.", { status: 404 });
  await prisma.release.update({ where: { id: release.id }, data: { downloads: { increment: 1 } } });
  return response;
}
