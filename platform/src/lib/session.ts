/**
 * Admin session: one platform password, an HMAC-signed cookie, verified by the proxy on every
 * request. Web Crypto so the same code runs in the Edge runtime the proxy executes in.
 */

export const SESSION_COOKIE = "player_session";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 14; // 14 days

const encoder = new TextEncoder();

function base64url(bytes: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(bytes));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function getSecret(): string {
  const secret = process.env.PLATFORM_SESSION_SECRET;
  if (!secret || secret.length < 16) {
    throw new Error("PLATFORM_SESSION_SECRET must be set to at least 16 characters");
  }
  return secret;
}

async function sign(payload: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(getSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return base64url(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
}

/** Constant-time comparison so a wrong signature leaks nothing through timing. */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(): Promise<string> {
  const issuedAt = Date.now().toString(36);
  return `${issuedAt}.${await sign(issuedAt)}`;
}

export async function verifySessionToken(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const [issuedAt, signature] = token.split(".");
  if (!issuedAt || !signature) return false;
  let expected: string;
  try {
    expected = await sign(issuedAt);
  } catch {
    return false;
  }
  if (!safeEqual(signature, expected)) return false;
  const issued = Number.parseInt(issuedAt, 36);
  if (!Number.isFinite(issued)) return false;
  return Date.now() - issued < MAX_AGE_SECONDS * 1000;
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  maxAge: MAX_AGE_SECONDS,
  secure: process.env.NODE_ENV === "production",
};
