import { NextResponse } from "next/server";
import { FILE_FORMAT, offlineFilesConfigured, publicKey } from "@/lib/offline";

export const runtime = "nodejs";

/** The key programs embed to verify offline licence files (RSASSA-PKCS1-v1_5, SHA-256). */
export async function GET() {
  if (!offlineFilesConfigured()) return NextResponse.json({ error: "offline files are not configured" }, { status: 404 });
  const key = publicKey();
  return NextResponse.json({ format: FILE_FORMAT, algorithm: "RSASSA-PKCS1-v1_5", hash: "SHA-256", n: key.n, e: key.e, pem: key.pem });
}
