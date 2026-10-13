import { NextResponse } from "next/server";
import { activate } from "@/lib/licensing";
import { clientIp, makeLimiter, readBody } from "@/lib/request";

export const runtime = "nodejs";

// Keys carry ~100 bits of entropy; the limiter just keeps a scanner from hammering the database.
const limited = makeLimiter(30, 10 * 60 * 1000);

export async function POST(request: Request) {
  const ip = clientIp(request);
  if (limited(ip)) {
    return NextResponse.json({ status: "invalid", message: "Too many attempts. Try again later." }, { status: 429 });
  }
  const { code, body } = await activate(await readBody(request), ip);
  return NextResponse.json(body, { status: code });
}
