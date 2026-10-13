/**
 * The device-facing rules: what a program gets back when it activates, checks in or
 * deactivates. Pure functions over the database so the route handlers stay thin.
 *
 * Statuses the program understands: active, locked, revoked, expired, unknown, no_seats,
 * invalid. `locked` keeps the registration (the admin can unlock); the rest make the
 * program ask for a key again.
 */
import { prisma } from "@/lib/db";
import { hashToken, makeToken, normaliseKey, tokenMatches } from "@/lib/keys";

export const DEFAULT_PRODUCT = "monitoring-application";

export type DeviceReply = { code: number; body: Record<string, unknown> };

export type DeviceInput = {
  key?: unknown;
  machine_id?: unknown;
  token?: unknown;
  hostname?: unknown;
  os?: unknown;
  version?: unknown;
  product?: unknown;
};

function str(v: unknown, max = 120): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function checkInterval(): number {
  const n = Number.parseInt(process.env.LICENSE_CHECK_INTERVAL ?? "", 10);
  return Number.isFinite(n) && n >= 30 ? n : 300;
}

function reply(code: number, status: string, message: string, extra: Record<string, unknown> = {}): DeviceReply {
  return { code, body: { status, message, interval: checkInterval(), ...extra } };
}

type LicenseRow = { id: string; status: string; expiresAt: Date | null; lockMessage: string | null; label: string; maxSeats: number; product: string };

function licenseVerdict(license: LicenseRow): DeviceReply | null {
  if (license.status === "revoked") return reply(403, "revoked", license.lockMessage || "This licence has been revoked.");
  if (license.expiresAt && license.expiresAt.getTime() < Date.now()) {
    return reply(403, "expired", `This licence expired on ${license.expiresAt.toISOString().slice(0, 10)}.`);
  }
  return null;
}

function okOrLocked(license: LicenseRow, system: { status: string; lockMessage: string | null }, extra: Record<string, unknown>): DeviceReply {
  if (license.status === "locked") {
    return reply(200, "locked", license.lockMessage || "This licence has been locked by the administrator.", extra);
  }
  if (system.status === "locked") {
    return reply(200, "locked", system.lockMessage || "This computer has been locked by the administrator.", extra);
  }
  return reply(200, "active", "", extra);
}

async function record(kind: string, licenseId: string | null, systemId: string | null, detail: string, ip: string) {
  await prisma.event.create({ data: { kind, licenseId, systemId, detail: detail.slice(0, 500), ip: ip.slice(0, 64) } });
}

export async function activate(input: DeviceInput, ip: string): Promise<DeviceReply> {
  const key = normaliseKey(input.key);
  const machineId = str(input.machine_id, 64);
  if (!key || !machineId) return reply(400, "invalid", "A licence key and a computer id are required.");
  const license = await prisma.license.findUnique({ where: { key } });
  if (!license) {
    await record("refused", null, null, `unknown key ${key.slice(-5)} from ${str(input.hostname)}`, ip);
    return reply(404, "invalid", "This licence key is not known. Check it and try again.");
  }
  const product = str(input.product) || DEFAULT_PRODUCT;
  if (license.product && license.product !== product) {
    return reply(403, "invalid", `This key is for ${license.product}, not ${product}.`);
  }
  const verdict = licenseVerdict(license);
  if (verdict) {
    await record("refused", license.id, null, `${verdict.body.status} key used by ${str(input.hostname)}`, ip);
    return verdict;
  }
  const details = { hostname: str(input.hostname, 80) || null, os: str(input.os, 80) || null, appVersion: str(input.version, 40) || null, ip, lastSeenAt: new Date() };
  let system = await prisma.system.findUnique({ where: { licenseId_machineId: { licenseId: license.id, machineId } } });
  if (!system) {
    const seats = await prisma.system.count({ where: { licenseId: license.id } });
    if (seats >= license.maxSeats) {
      await record("refused", license.id, null, `no seats left for ${details.hostname ?? machineId}`, ip);
      return reply(403, "no_seats", `All ${license.maxSeats} seat${license.maxSeats === 1 ? "" : "s"} of this licence are in use. Remove a computer on the platform first.`);
    }
    system = await prisma.system.create({ data: { licenseId: license.id, machineId, tokenHash: "pending", ...details } });
    await record("activated", license.id, system.id, `${details.hostname ?? machineId} (${details.os ?? "?"}) v${details.appVersion ?? "?"}`, ip);
  } else {
    await record("activated", license.id, system.id, `re-activated ${details.hostname ?? machineId}`, ip);
  }
  const token = makeToken(license.id, machineId, system.id);
  system = await prisma.system.update({ where: { id: system.id }, data: { tokenHash: hashToken(token), ...details } });
  return okOrLocked(license, system, { token, label: license.label, expires_at: license.expiresAt?.toISOString() ?? null });
}

export async function heartbeat(input: DeviceInput, ip: string): Promise<DeviceReply> {
  const key = normaliseKey(input.key);
  const machineId = str(input.machine_id, 64);
  if (!key || !machineId) return reply(400, "invalid", "A licence key and a computer id are required.");
  const license = await prisma.license.findUnique({ where: { key } });
  if (!license) return reply(404, "invalid", "This licence key is no longer known.");
  const system = await prisma.system.findUnique({ where: { licenseId_machineId: { licenseId: license.id, machineId } } });
  if (!system) return reply(404, "unknown", "This computer is not registered to the licence any more. Activate it again.");
  if (!tokenMatches(input.token, system.tokenHash)) {
    return reply(401, "unknown", "The activation on this computer is no longer valid. Activate it again.");
  }
  const verdict = licenseVerdict(license);
  const updated = await prisma.system.update({
    where: { id: system.id },
    data: {
      lastSeenAt: new Date(),
      ip,
      hostname: str(input.hostname, 80) || system.hostname,
      appVersion: str(input.version, 40) || system.appVersion,
    },
  });
  if (verdict) return verdict;
  return okOrLocked(license, updated, { label: license.label, expires_at: license.expiresAt?.toISOString() ?? null });
}

export async function deactivate(input: DeviceInput, ip: string): Promise<DeviceReply> {
  const key = normaliseKey(input.key);
  const machineId = str(input.machine_id, 64);
  if (!key || !machineId) return reply(400, "invalid", "A licence key and a computer id are required.");
  const license = await prisma.license.findUnique({ where: { key } });
  if (!license) return reply(404, "invalid", "Unknown licence key.");
  const system = await prisma.system.findUnique({ where: { licenseId_machineId: { licenseId: license.id, machineId } } });
  if (!system) return reply(200, "ok", "This computer was not registered.");
  if (!tokenMatches(input.token, system.tokenHash)) return reply(401, "unknown", "Invalid activation token.");
  await prisma.system.delete({ where: { id: system.id } });
  await record("deactivated", license.id, system.id, `${system.hostname ?? machineId} deactivated itself`, ip);
  return reply(200, "ok", "Deactivated.");
}

/** A computer counts as online when it has checked in within two intervals. */
export function isOnline(lastSeenAt: Date): boolean {
  return Date.now() - lastSeenAt.getTime() < checkInterval() * 2 * 1000;
}
