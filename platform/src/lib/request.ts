import { NextResponse } from "next/server";

export function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  return forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip") || "unknown";
}

/** Body as an object whether it came as JSON or as an HTML form. */
export async function readBody(request: Request): Promise<Record<string, unknown>> {
  const type = request.headers.get("content-type") ?? "";
  try {
    if (type.includes("application/json")) {
      const body = await request.json();
      return body && typeof body === "object" ? (body as Record<string, unknown>) : {};
    }
    const form = await request.formData();
    const out: Record<string, unknown> = {};
    form.forEach((value, name) => {
      if (typeof value === "string") out[name] = value;
    });
    return out;
  } catch {
    return {};
  }
}

export function wantsJson(request: Request): boolean {
  const accept = request.headers.get("accept") ?? "";
  const type = request.headers.get("content-type") ?? "";
  return type.includes("application/json") || (accept.includes("application/json") && !accept.includes("text/html"));
}

/**
 * The origin the browser used. Behind Railway's proxy `request.url` in a route handler is the
 * server's own listen address (https://localhost:8080), so a redirect built from it leaves the site.
 * Prefer the forwarded headers the proxy sets, then the Host header, then `request.url`.
 */
export function publicOrigin(request: Request): string {
  const first = (name: string) => request.headers.get(name)?.split(",")[0]?.trim() || "";
  const host = first("x-forwarded-host") || first("host");
  if (!host) return new URL(request.url).origin;
  const local = /^(localhost|127\.0\.0\.1|\[::1\])(:|$)/.test(host);
  const proto = first("x-forwarded-proto") || (local ? "http" : "https");
  return `${proto}://${host}`;
}

/** Redirect to a path on this site (303 by default, so a form POST becomes a GET). */
export function redirectTo(request: Request, location: string, status = 303) {
  return NextResponse.redirect(new URL(location, publicOrigin(request)), status);
}

/** Only same-site paths are allowed as a post-login destination. */
export function safePath(value: unknown, fallback = "/"): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\")
    ? value
    : fallback;
}

/** Admin endpoints: JSON for API callers, a redirect back to the page for HTML forms. */
export function done(request: Request, location: string, payload: Record<string, unknown> = { ok: true }, status = 200) {
  if (wantsJson(request)) return NextResponse.json(payload, { status });
  return redirectTo(request, location);
}

/** A small in-memory limiter: per key, `max` hits per `windowMs`. Per instance, which is enough here. */
export function makeLimiter(max: number, windowMs: number) {
  const hits = new Map<string, { count: number; firstAt: number }>();
  return (key: string): boolean => {
    const now = Date.now();
    const entry = hits.get(key);
    if (!entry || now - entry.firstAt > windowMs) {
      hits.set(key, { count: 1, firstAt: now });
      return false;
    }
    entry.count += 1;
    return entry.count > max;
  };
}
