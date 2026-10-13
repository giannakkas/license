import { NextResponse } from "next/server";
import { clientIp, makeLimiter, readBody, wantsJson } from "@/lib/request";
import { SESSION_COOKIE, createSessionToken, safeEqual, sessionCookieOptions } from "@/lib/session";

export const runtime = "nodejs";

const limited = makeLimiter(10, 10 * 60 * 1000);

export async function POST(request: Request) {
  const expected = process.env.PLATFORM_ADMIN_PASSWORD;
  if (!expected) {
    return NextResponse.json({ error: "PLATFORM_ADMIN_PASSWORD is not configured" }, { status: 500 });
  }
  const ip = clientIp(request);
  const body = await readBody(request);
  const password = typeof body.password === "string" ? body.password : "";
  const next = typeof body.next === "string" && body.next.startsWith("/") ? body.next : "/";
  const fail = (message: string, status: number) =>
    wantsJson(request)
      ? NextResponse.json({ error: message }, { status })
      : NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(message)}`, request.url), 303);

  if (limited(ip)) return fail("Too many attempts. Try again in a few minutes.", 429);
  if (!safeEqual(password, expected)) return fail("Wrong password", 401);

  const response = wantsJson(request)
    ? NextResponse.json({ ok: true })
    : NextResponse.redirect(new URL(next, request.url), 303);
  response.cookies.set(SESSION_COOKIE, await createSessionToken(), sessionCookieOptions);
  return response;
}
