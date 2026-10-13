export function timeAgo(date: Date | null | undefined): string {
  if (!date) return "never";
  const s = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtDate(date: Date | null | undefined): string {
  if (!date) return "—";
  return date.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function fmtDay(date: Date | null | undefined): string {
  return date ? date.toISOString().slice(0, 10) : "";
}

export function isExpired(date: Date | null | undefined): boolean {
  return !!date && date.getTime() < Date.now();
}
