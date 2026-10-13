/** Field parsing shared by the admin endpoints (HTML forms and JSON alike). */

export function field(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

export function parseSeats(value: unknown, fallback = 1): number {
  const n = Number.parseInt(String(value ?? ""), 10);
  return Math.max(1, Math.min(500, Number.isFinite(n) ? n : fallback));
}

/** "YYYY-MM-DD" → the end of that day (UTC); "" → no expiry; anything else → invalid. */
export function parseExpiry(value: unknown): { ok: true; date: Date | null } | { ok: false; date: null } {
  const raw = field(value, 20);
  if (!raw) return { ok: true, date: null };
  const date = new Date(`${raw}T23:59:59Z`);
  return Number.isNaN(date.getTime()) ? { ok: false, date: null } : { ok: true, date };
}
