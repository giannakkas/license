import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/** Crockford-style alphabet: no 0/O or 1/I/L, so a key read over the phone survives. */
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
export const KEY_PREFIX = "ONCUE";
export const KEY_GROUPS = 4;
export const KEY_GROUP_LENGTH = 5;

export function generateKey(): string {
  const bytes = randomBytes(KEY_GROUPS * KEY_GROUP_LENGTH);
  let raw = "";
  for (const b of bytes) raw += ALPHABET[b % ALPHABET.length];
  const groups: string[] = [];
  for (let i = 0; i < raw.length; i += KEY_GROUP_LENGTH) groups.push(raw.slice(i, i + KEY_GROUP_LENGTH));
  return `${KEY_PREFIX}-${groups.join("-")}`;
}

/** Upper-case, drop separators, re-group; returns "" when the input cannot be a key. */
export function normaliseKey(text: unknown): string {
  if (typeof text !== "string") return "";
  let raw = text.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (raw.startsWith(KEY_PREFIX)) raw = raw.slice(KEY_PREFIX.length);
  if (raw.length !== KEY_GROUPS * KEY_GROUP_LENGTH) return "";
  const groups: string[] = [];
  for (let i = 0; i < raw.length; i += KEY_GROUP_LENGTH) groups.push(raw.slice(i, i + KEY_GROUP_LENGTH));
  return `${KEY_PREFIX}-${groups.join("-")}`;
}

function signingSecret(): string {
  const secret = process.env.LICENSE_SIGNING_SECRET;
  if (!secret || secret.length < 16) throw new Error("LICENSE_SIGNING_SECRET must be set to at least 16 characters");
  return secret;
}

/** The activation token a program holds: proves the platform registered this machine. */
export function makeToken(licenseId: string, machineId: string, systemId: string): string {
  return createHmac("sha256", signingSecret()).update(`${licenseId}:${machineId}:${systemId}`).digest("hex");
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function tokenMatches(token: unknown, tokenHash: string): boolean {
  if (typeof token !== "string" || !token) return false;
  const a = Buffer.from(hashToken(token));
  const b = Buffer.from(tokenHash);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function maskKey(key: string): string {
  return key.length > 5 ? `${KEY_PREFIX}-•••••-•••••-•••••-${key.slice(-5)}` : key;
}
