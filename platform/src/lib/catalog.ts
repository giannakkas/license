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

/** What a program shows as "Licensed to": the customer, plus the reference when there is one. */
export function licensedTo(license: { label: string | null; customer: { name: string } }): string {
  return license.label ? `${license.customer.name} – ${license.label}` : license.customer.name;
}
