import Link from "next/link";
import { Badge } from "@/components/badge";
import { prisma } from "@/lib/db";
import { fmtDay, isExpired, timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";

export const dynamic = "force-dynamic";

export default async function Dashboard({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const licenses = await prisma.license.findMany({
    orderBy: { createdAt: "desc" },
    include: { systems: { select: { status: true, lastSeenAt: true } } },
  });
  const online = licenses.reduce((n, l) => n + l.systems.filter((s) => isOnline(s.lastSeenAt)).length, 0);
  const locked = licenses.filter((l) => l.status === "locked").length + licenses.reduce((n, l) => n + l.systems.filter((s) => s.status === "locked").length, 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Licences" value={licenses.length} />
        <Stat label="Computers online" value={online} />
        <Stat label="Locked" value={locked} tone={locked ? "red" : undefined} />
        <Stat label="Revoked" value={licenses.filter((l) => l.status === "revoked").length} />
      </div>

      {error && <p className="rounded border border-[#7a2323] bg-[#3a1416] px-3 py-2 text-sm text-[#fca5a5]">{error}</p>}

      <section className="panel">
        <div className="flex items-center justify-between border-b border-[#2a2f3a] px-4 py-3">
          <h2 className="font-bold">Licences</h2>
          <span className="muted text-xs">Click a key to open it</span>
        </div>
        {licenses.length === 0 ? (
          <p className="muted px-4 py-6 text-sm">No licences yet. Create the first one below.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Key</th><th>Licensed to</th><th>Status</th><th>Computers</th><th>Last seen</th><th>Expires</th>
              </tr>
            </thead>
            <tbody>
              {licenses.map((l) => {
                const last = l.systems.reduce<Date | null>((m, s) => (!m || s.lastSeenAt > m ? s.lastSeenAt : m), null);
                const lockedSystems = l.systems.filter((s) => s.status === "locked").length;
                const expired = isExpired(l.expiresAt);
                return (
                  <tr key={l.id}>
                    <td><Link href={`/licenses/${l.id}`} className="mono font-semibold hover:underline">{l.key}</Link></td>
                    <td>{l.label}<div className="muted text-xs">{l.product}</div></td>
                    <td><Badge status={expired && l.status === "active" ? "expired" : l.status} /></td>
                    <td>
                      {l.systems.length} / {l.maxSeats}
                      {lockedSystems > 0 && <span className="ml-2 text-xs text-[#fca5a5]">{lockedSystems} locked</span>}
                    </td>
                    <td className={last && isOnline(last) ? "text-[#4ade80]" : "muted"}>{timeAgo(last)}</td>
                    <td className={expired ? "text-[#fcd34d]" : "muted"}>{l.expiresAt ? fmtDay(l.expiresAt) : "never"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-bold">New licence</h2>
        <form method="post" action="/api/admin/licenses" className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_auto]">
          <label className="flex flex-col gap-1 text-sm">
            Licensed to
            <input name="label" placeholder="Customer, studio or person" required />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Computers allowed
            <input name="maxSeats" type="number" min={1} max={500} defaultValue={1} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Expires (optional)
            <input name="expiresAt" type="date" />
          </label>
          <div className="flex items-end">
            <button type="submit" className="btn btn-primary">Create key</button>
          </div>
          <label className="flex flex-col gap-1 text-sm md:col-span-4">
            Notes (optional)
            <input name="notes" placeholder="Invoice number, contact, anything useful" />
          </label>
          <input type="hidden" name="product" value="monitoring-application" />
        </form>
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "red" }) {
  return (
    <div className="panel px-4 py-3">
      <div className="muted text-xs uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold ${tone === "red" ? "text-[#fca5a5]" : ""}`}>{value}</div>
    </div>
  );
}
