import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { field } from "@/lib/forms";
import { fmtSize, removeFile, safeFilename, storeUpload } from "@/lib/releases";
import { clientIp } from "@/lib/request";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

export const runtime = "nodejs";

function header(request: Request, name: string): string {
  try {
    return decodeURIComponent(request.headers.get(name) ?? "");
  } catch {
    return "";
  }
}

/**
 * Upload a build: the raw file as the request body, with x-filename, x-version, x-notes and
 * x-size headers (URL-encoded). Streams to the downloads volume; answers the new release.
 * This path is outside the proxy (see proxy.ts), so the admin session is checked here.
 */
export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await verifySessionToken((await cookies()).get(SESSION_COOKIE)?.value))) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }
  const { id } = await params;
  const product = await prisma.product.findUnique({ where: { id } });
  if (!product) return NextResponse.json({ error: "Software not found" }, { status: 404 });
  const filename = safeFilename(header(request, "x-filename"));
  const version = field(header(request, "x-version"), 40);
  const notes = field(header(request, "x-notes"), 500) || null;
  if (!version) return NextResponse.json({ error: "A version is required" }, { status: 400 });
  if (!request.body) return NextResponse.json({ error: "No file was sent" }, { status: 400 });
  const declared = Number.parseInt(header(request, "x-size") || request.headers.get("content-length") || "", 10);
  const release = await prisma.release.create({ data: { productId: id, version, filename, size: 0, sha256: "", notes } });
  let stored: { size: number; sha256: string };
  try {
    stored = await storeUpload(id, release.id, filename, request.body);
    if (stored.size === 0) throw new Error("the file is empty");
    if (Number.isFinite(declared) && declared > 0 && stored.size !== declared) {
      throw new Error(`only ${fmtSize(stored.size)} of ${fmtSize(declared)} arrived; try again`);
    }
  } catch (error) {
    await removeFile(id, release.id, filename);
    await prisma.release.delete({ where: { id: release.id } });
    return NextResponse.json({ error: `Upload failed: ${(error as Error).message}` }, { status: 500 });
  }
  await prisma.release.update({ where: { id: release.id }, data: { size: stored.size, sha256: stored.sha256 } });
  await prisma.event.create({
    data: { kind: "release", detail: `${product.name} ${version} uploaded (${filename}, ${fmtSize(stored.size)})`, ip: clientIp(request) },
  });
  return NextResponse.json({ ok: true, id: release.id, version, filename, size: stored.size, sha256: stored.sha256 }, { status: 201 });
}
