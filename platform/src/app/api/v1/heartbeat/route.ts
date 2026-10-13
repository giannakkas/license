import { NextResponse } from "next/server";
import { heartbeat } from "@/lib/licensing";
import { clientIp, readBody } from "@/lib/request";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const { code, body } = await heartbeat(await readBody(request), clientIp(request));
  return NextResponse.json(body, { status: code });
}
