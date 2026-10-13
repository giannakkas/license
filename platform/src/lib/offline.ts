/**
 * Offline licence files: a signed payload a computer without internet imports instead of
 * activating online. Signed with the platform's RSA-2048 key (LICENSE_FILE_PRIVATE_KEY,
 * base64 PKCS#8 DER); the programs carry the public modulus and verify with
 * RSASSA-PKCS1-v1_5 / SHA-256. Re-signing an identical payload gives the identical signature,
 * which the platform stores (hashed) as the computer's check-in token.
 */
import { createPrivateKey, createPublicKey, sign, type KeyObject } from "node:crypto";
import { prisma } from "@/lib/db";
import { hashToken } from "@/lib/keys";
import { checkInterval } from "@/lib/licensing";

export const FILE_FORMAT = "oncue-licence/1";

let cached: { priv: KeyObject; pub: KeyObject } | null = null;

function keys() {
  if (cached) return cached;
  const raw = process.env.LICENSE_FILE_PRIVATE_KEY?.trim();
  if (!raw) throw new Error("LICENSE_FILE_PRIVATE_KEY is not set (see README: offline licence files)");
  const priv = createPrivateKey({ key: Buffer.from(raw, "base64"), format: "der", type: "pkcs8" });
  cached = { priv, pub: createPublicKey(priv) };
  return cached;
}

export function offlineFilesConfigured(): boolean {
  return Boolean(process.env.LICENSE_FILE_PRIVATE_KEY?.trim());
}

/** The public key in the two forms a program may want: JWK modulus/exponent and SPKI PEM. */
export function publicKey(): { n: string; e: string; pem: string } {
  const { pub } = keys();
  const jwk = pub.export({ format: "jwk" }) as { n: string; e: string };
  return { n: jwk.n, e: jwk.e, pem: pub.export({ type: "spki", format: "pem" }) as string };
}

export type FilePayload = {
  v: 1;
  license_id: string;
  system_id: string;
  key: string;
  product: string;
  product_name: string;
  customer: string;
  label: string;
  machine_id: string;
  hostname: string;
  issued_at: string;
  expires_at: string;
  server: string;
  interval: number;
};

export function issueLicenseFile(payload: FilePayload): { content: string; signature: string; filename: string } {
  const bytes = Buffer.from(JSON.stringify(payload), "utf8");
  const signature = sign("sha256", bytes, keys().priv).toString("base64url");
  const content = `${JSON.stringify({ format: FILE_FORMAT, payload: bytes.toString("base64url"), signature }, null, 2)}\n`;
  return { content, signature, filename: `${payload.product}-${payload.machine_id}.lic` };
}

/** Computer ids are 20 upper-case letters/digits (the program shows them as such). */
export function normaliseMachineId(value: unknown): string {
  const id = typeof value === "string" ? value.toUpperCase().replace(/[^A-Z0-9]/g, "") : "";
  return id.length === 20 ? id : "";
}

type FileLicense = { id: string; key: string; label: string | null; expiresAt: Date | null; product: { slug: string; name: string }; customer: { name: string } };
type FileSystem = { id: string; machineId: string; hostname: string | null; firstSeenAt: Date; offlineExpiresAt: Date | null };

/**
 * Build, sign and record the file for one offline computer. The signature (hashed) becomes the
 * computer's check-in token, so a computer that does reach the platform is recognised. An
 * unchanged licence re-signs to the identical file; after a change (new expiry, renamed
 * customer) the computer needs the new file.
 */
export async function issueForSystem(license: FileLicense, system: FileSystem, server: string) {
  const expires = system.offlineExpiresAt ?? license.expiresAt;
  if (!expires) throw new Error("an offline file needs an expiry date");
  const payload: FilePayload = {
    v: 1,
    license_id: license.id,
    system_id: system.id,
    key: license.key,
    product: license.product.slug,
    product_name: license.product.name,
    customer: license.customer.name,
    label: license.label ?? "",
    machine_id: system.machineId,
    hostname: system.hostname ?? "",
    issued_at: system.firstSeenAt.toISOString(),
    expires_at: expires.toISOString(),
    server,
    interval: checkInterval(),
  };
  const file = issueLicenseFile(payload);
  await prisma.system.update({ where: { id: system.id }, data: { tokenHash: hashToken(file.signature) } });
  return { ...file, expires };
}

export function fileResponse(file: { content: string; filename: string }): Response {
  return new Response(file.content, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "content-disposition": `attachment; filename="${file.filename}"`,
      "cache-control": "no-store",
    },
  });
}
