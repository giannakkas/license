import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fileResponse, issueForSystem, offlineFilesConfigured } from "@/lib/offline";
import { publicOrigin } from "@/lib/request";

export const runtime = "nodejs";

/** The current offline licence file for a computer (re-signed from the licence as it is now). */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!offlineFilesConfigured()) return NextResponse.json({ error: "offline files are not configured" }, { status: 503 });
  const system = await prisma.system.findUnique({ where: { id }, include: { license: { include: { product: true, customer: true } } } });
  if (!system || system.mode !== "offline") return NextResponse.json({ error: "This computer has no offline file" }, { status: 404 });
  if (system.license.status === "revoked") return NextResponse.json({ error: "The licence is revoked" }, { status: 409 });
  const file = await issueForSystem(system.license, system, process.env.PUBLIC_URL || publicOrigin(request));
  return fileResponse(file);
}
