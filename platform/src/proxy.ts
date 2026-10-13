import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

/**
 * Next 16 calls this file `proxy.ts` (formerly middleware.ts).
 * The admin screens and admin API sit behind the platform password. The device API
 * (/api/v1/*) is authenticated by licence key and activation token instead, and the build
 * downloads (/download/*) are public: the files are useless without a licence.
 */
export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const isPublic =
    pathname === "/login" ||
    pathname === "/api/auth/login" ||
    pathname === "/api/health" ||
    pathname.startsWith("/api/v1/") ||
    pathname.startsWith("/download/");

  if (isPublic) return NextResponse.next();

  const authed = await verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value);
  if (authed) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }

  const loginUrl = new URL("/login", request.url);
  if (pathname !== "/") loginUrl.searchParams.set("next", pathname + search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|webp|ico)$).*)"],
};
