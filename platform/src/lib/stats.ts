import { isExpired } from "@/lib/format";
import { isOnline } from "@/lib/licensing";

export type LicenseSummaryRow = { status: string; expiresAt: Date | null; systems: { status: string; lastSeenAt: Date; mode?: string }[] };

/** Counts for a set of licences: the dashboard tiles and the per-customer / per-software rows. */
export function summarise(licenses: LicenseSummaryRow[]) {
  let computers = 0;
  let online = 0;
  let locked = 0;
  let revoked = 0;
  let expired = 0;
  let files = 0;
  for (const l of licenses) {
    computers += l.systems.length;
    files += l.systems.filter((s) => s.mode === "offline").length;
    online += l.systems.filter((s) => isOnline(s.lastSeenAt)).length;
    locked += (l.status === "locked" ? 1 : 0) + l.systems.filter((s) => s.status === "locked").length;
    if (l.status === "revoked") revoked += 1;
    else if (isExpired(l.expiresAt)) expired += 1;
  }
  return { licences: licenses.length, computers, online, locked, revoked, expired, files };
}

/** The badge for a licence: an active one past its date shows as expired. */
export function effectiveStatus(l: { status: string; expiresAt: Date | null }): string {
  return l.status === "active" && isExpired(l.expiresAt) ? "expired" : l.status;
}

export function latestSeen(systems: { lastSeenAt: Date }[]): Date | null {
  return systems.reduce<Date | null>((m, s) => (!m || s.lastSeenAt > m ? s.lastSeenAt : m), null);
}
