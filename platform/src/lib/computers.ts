/** Computers (activated systems) across licences: one query shape for the fleet views, plus version status. */
import type { SystemGetPayload, SystemWhereInput } from "@/generated/prisma/models";
import { isNewer, versionParts } from "@/lib/catalog";
import { prisma } from "@/lib/db";
import { checkInterval } from "@/lib/licensing";

export const COMPUTER_INCLUDE = {
  license: {
    select: {
      id: true,
      key: true,
      label: true,
      status: true,
      customer: { select: { id: true, name: true } },
      product: {
        select: {
          id: true,
          name: true,
          slug: true,
          minVersion: true,
          releases: { orderBy: { createdAt: "desc" as const }, take: 1, select: { version: true } },
        },
      },
    },
  },
} as const;

export type ComputerRow = SystemGetPayload<{ include: typeof COMPUTER_INCLUDE }>;

export function loadComputers(where: SystemWhereInput = {}) {
  return prisma.system.findMany({ where, include: COMPUTER_INCLUDE, orderBy: { lastSeenAt: "desc" } });
}

export type VersionState = "current" | "outdated" | "required" | "unknown";

/** Where a computer stands against its software's newest build and minimum version. */
export function versionState(c: ComputerRow): VersionState {
  const latest = c.license.product.releases[0]?.version;
  if (!c.appVersion || !latest) return "unknown";
  const min = c.license.product.minVersion;
  if (min && isNewer(min, c.appVersion)) return "required";
  return isNewer(latest, c.appVersion) ? "outdated" : "current";
}

export type VersionGroup = {
  product: { id: string; name: string };
  latest: string | null;
  total: number;
  versions: { version: string; count: number; state: VersionState }[];
};

/** Per software: how many computers run each version, newest first. */
export function versionSummary(computers: ComputerRow[]): VersionGroup[] {
  const groups = new Map<string, VersionGroup>();
  for (const c of computers) {
    const p = c.license.product;
    let g = groups.get(p.id);
    if (!g) {
      g = { product: { id: p.id, name: p.name }, latest: p.releases[0]?.version ?? null, total: 0, versions: [] };
      groups.set(p.id, g);
    }
    g.total += 1;
    const version = c.appVersion || "not reported";
    const row = g.versions.find((v) => v.version === version);
    if (row) row.count += 1;
    else g.versions.push({ version, count: 1, state: versionState(c) });
  }
  const byVersionDesc = (a: { version: string }, b: { version: string }) => {
    const x = versionParts(a.version);
    const y = versionParts(b.version);
    for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
      const d = (y[i] ?? 0) - (x[i] ?? 0);
      if (d !== 0) return d;
    }
    return 0;
  };
  return [...groups.values()]
    .map((g) => ({ ...g, versions: g.versions.sort(byVersionDesc) }))
    .sort((a, b) => a.product.name.localeCompare(b.product.name));
}

/** The first version of each software that waits for news from the platform, so a lock shows within seconds. */
const INSTANT_LOCK_FROM: Record<string, string> = { "monitoring-application": "1.4.3" };

/** When a lock (or unlock) reaches a computer, for the confirmation text: "within a few seconds", ... */
export function lockArrives(c: { appVersion: string | null; online: boolean; product: { slug: string } }): string {
  if (!c.online) return "when it next connects to the platform";
  const from = INSTANT_LOCK_FROM[c.product.slug];
  if (from && c.appVersion && !isNewer(from, c.appVersion)) return "within a few seconds";
  return `at its next check-in, within ${Math.round(checkInterval() / 60)} minutes`;
}
