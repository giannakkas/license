import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { fmtSize, safeFilename, storeUpload } from "@/lib/releases";
import { clientIp } from "@/lib/request";

export const runtime = "nodejs";

function header(request: Request, name: string): string {
  try {
    return decodeURIComponent(request.headers.get(name) ?? "");
  } catch {
    return "";
  }
}

/**
 * Upload a build: the raw file as the request body, with x-filename, x-version and x-notes
 * headers (URL-encoded). Streams to the downloads volume; answers the new release.
 */
export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = await prisma.product.findUnique({ where: { id } });
  if (!product) return NextResponse.json({ error: "Software not found" }, { status: 404 });
  const filename = safeFilename(header(request, "x-filename"));
  const version = field(header(request, "x-version"), 40);
  const notes = field(header(request, "x-notes"), 500) || null;
  if (!version) return NextResponse.json({ error: "A version is required" }, { status: 400 });
  if (!request.body) return NextResponse.json({ error: "No file was sent" }, { status: 400 });
  const release = await prisma.release.create({ data: { productId: id, version, filename, size: 0, sha256: "", notes } });
  let stored: { size: number; sha256: string };
  try {
    stored = await storeUpload(id, release.id, filename, request.body);
    if (stored.size === 0) throw new Error("the file is empty");
  } catch (error) {
    await prisma.release.delete({ where: { id: release.id } });
    return NextResponse.json({ error: `Upload failed: ${(error as Error).message}` }, { status: 500 });
  }
  await prisma.release.update({ where: { id: release.id }, data: { size: stored.size, sha256: stored.sha256 } });
  await prisma.event.create({
    data: { kind: "release", detail: `${product.name} ${version} uploaded (${filename}, ${fmtSize(stored.size)})`, ip: clientIp(request) },
  });
  return NextResponse.json({ ok: true, id: release.id, version, filename, size: stored.size, sha256: stored.sha256 }, { status: 201 });
}
