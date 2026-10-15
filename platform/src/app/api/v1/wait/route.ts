import { NextResponse } from "next/server";
import { waitForChange } from "@/lib/licensing";
import { readBody } from "@/lib/request";

export const runtime = "nodejs";

/** Held open by the program until its licence or computer changes, so a lock shows within seconds. */
export async function POST(request: Request) {
  const { code, body } = await waitForChange(await readBody(request), request.signal);
  return NextResponse.json(body, { status: code, headers: { "cache-control": "no-store" } });
}
