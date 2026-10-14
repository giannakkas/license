/** Softwares (products) and customers: naming rules and the text the programs display. */

/** The slug the Monitoring Application sends; also assumed when an old build sends none. */
export const DEFAULT_PRODUCT_SLUG = "monitoring-application";

/** Lower-case letters, digits and dashes, 2–60 characters. */
export const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,59}$/;

/** "Playout Server 2" → "playout-server-2". */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** "1.4.0" -> [1, 4, 0]; text without digits -> [0]. */
export function versionParts(text: string | null | undefined): number[] {
  const parts = (String(text ?? "").match(/\d+/g) ?? []).slice(0, 4).map(Number);
  return parts.length ? parts : [0];
}

/** True when `candidate` is a higher version than `current`. */
export function isNewer(candidate: string | null | undefined, current: string | null | undefined): boolean {
  const a = versionParts(candidate);
  const b = versionParts(current);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (d !== 0) return d > 0;
  }
  return false;
}

export const VERSION_RE = /^\d+(\.\d+){0,3}$/;

/** What a program shows as "Licensed to": the customer, plus the reference when there is one. */
export function licensedTo(license: { label: string | null; customer: { name: string } }): string {
  return license.label ? `${license.customer.name} – ${license.label}` : license.customer.name;
}
