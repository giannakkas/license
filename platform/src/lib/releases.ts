/**
 * Downloadable builds: files on the downloads volume (DOWNLOADS_DIR, /data/downloads on
 * Railway), one folder per software, named <releaseId>-<filename>. Uploads stream straight
 * to disk while a SHA-256 is computed; downloads stream back with the original file name.
 */
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, rename, rm, stat } from "node:fs/promises";
import path from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as NodeReadableStream } from "node:stream/web";

export function downloadsDir(): string {
  return process.env.DOWNLOADS_DIR || path.join(process.cwd(), "data", "downloads");
}

export function safeFilename(name: string): string {
  const base = name.replace(/^.*[\\/]/, "").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^\.+/, "").slice(0, 120);
  return base || "download.bin";
}

export function releasePath(productId: string, releaseId: string, filename: string): string {
  return path.join(downloadsDir(), productId, `${releaseId}-${filename}`);
}

export async function storeUpload(productId: string, releaseId: string, filename: string, body: ReadableStream<Uint8Array>) {
  const dir = path.join(downloadsDir(), productId);
  await mkdir(dir, { recursive: true });
  const final = releasePath(productId, releaseId, filename);
  const tmp = `${final}.part`;
  const hash = createHash("sha256");
  let size = 0;
  const hasher = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      hash.update(chunk);
      size += chunk.length;
      callback(null, chunk);
    },
  });
  try {
    await pipeline(Readable.fromWeb(body as NodeReadableStream<Uint8Array>), hasher, createWriteStream(tmp));
    await rename(tmp, final);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
  return { size, sha256: hash.digest("hex") };
}

export async function removeFile(productId: string, releaseId: string, filename: string): Promise<void> {
  await rm(releasePath(productId, releaseId, filename), { force: true });
}

/** Stream a stored build back as an attachment; null when the file is missing on disk. */
export async function fileDownload(productId: string, releaseId: string, filename: string): Promise<Response | null> {
  const file = releasePath(productId, releaseId, filename);
  let info;
  try {
    info = await stat(file);
  } catch {
    return null;
  }
  const stream = Readable.toWeb(createReadStream(file)) as unknown as ReadableStream;
  return new Response(stream, {
    headers: {
      "content-type": "application/octet-stream",
      "content-length": String(info.size),
      "content-disposition": `attachment; filename="${filename}"`,
      "cache-control": "no-store",
    },
  });
}

export function fmtSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}
