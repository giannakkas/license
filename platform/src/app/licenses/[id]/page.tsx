import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/badge";
import { ConfirmButton } from "@/components/confirm-button";
import { ErrorBox } from "@/components/error-box";
import { prisma } from "@/lib/db";
import { fmtDate, fmtDay, timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";
import { effectiveStatus } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function LicensePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  const [license, products, customers] = await Promise.all([
    prisma.license.findUnique({
      where: { id },
      include: {
        product: { select: { id: true, name: true, slug: true } },
        customer: { select: { id: true, name: true } },
        systems: { orderBy: { lastSeenAt: "desc" } },
        events: { orderBy: { createdAt: "desc" }, take: 50 },
      },
    }),
    prisma.product.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
    prisma.customer.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
  ]);
  if (!license) notFound();
  const action = `/api/admin/licenses/${license.id}`;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/" className="muted text-sm hover:underline">← Licences</Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold">
            <Link href={`/customers/${license.customer.id}`} className="hover:underline">{license.customer.name}</Link>
            {license.label && <span className="muted font-normal"> · {license.label}</span>}
          </h1>
          <Badge status={effectiveStatus(license)} />
          <Link href={`/products/${license.product.id}`} className="muted text-sm hover:underline">{license.product.name}</Link>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <code className="mono rounded border border-[#2a2f3a] bg-[#1e222b] px-3 py-1.5 text-lg font-bold tracking-wide select-all">{license.key}</code>
          <span className="muted text-xs">Give this key to the operator; the program asks for it on first start.</span>
        </div>
        {license.lockMessage && (license.status === "locked" || license.status === "revoked") && (
          <p className="mt-2 text-sm text-[#fca5a5]">Message shown on the computers: “{license.lockMessage}”</p>
        )}
      </div>

      <ErrorBox message={error} />

      <section className="grid gap-4 md:grid-cols-2">
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">Lock or revoke</h2>
          <p className="muted mb-3 text-sm">
            <b>Lock</b> stops every computer on this licence within one check-in and keeps their registrations;
            <b> Revoke</b> ends the licence and the programs ask for a new key.
          </p>
          <form method="post" action={action} className="flex flex-col gap-2">
            <input name="message" placeholder="Message shown on the locked screens (optional)" defaultValue={license.lockMessage ?? ""} />
            <div className="flex flex-wrap gap-2">
              {license.status === "active" && <button className="btn btn-danger" name="action" value="lock">Lock licence</button>}
              {license.status === "locked" && <button className="btn btn-primary" name="action" value="unlock">Unlock licence</button>}
              {license.status !== "revoked" && <button className="btn btn-danger" name="action" value="revoke">Revoke</button>}
              {license.status === "revoked" && <button className="btn btn-primary" name="action" value="reinstate">Reinstate</button>}
            </div>
          </form>
        </div>
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">Details</h2>
          <form method="post" action={action} className="grid grid-cols-2 gap-2 text-sm">
            <input type="hidden" name="action" value="update" />
            <label className="flex flex-col gap-1">
              Customer
              <select name="customerId" defaultValue={license.customerId}>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              Software
              <select name="productId" defaultValue={license.productId}>
                {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              Reference
              <input name="label" defaultValue={license.label ?? ""} placeholder="Site, studio, invoice number (optional)" />
            </label>
            <label className="flex flex-col gap-1">Computers allowed<input name="maxSeats" type="number" min={1} max={500} defaultValue={license.maxSeats} /></label>
            <label className="flex flex-col gap-1">Expires<input name="expiresAt" type="date" defaultValue={fmtDay(license.expiresAt)} /></label>
            <label className="col-span-2 flex flex-col gap-1">Notes<textarea name="notes" rows={2} defaultValue={license.notes ?? ""} /></label>
            <div className="col-span-2 flex items-center justify-between">
              <button type="submit" className="btn">Save</button>
              <span className="muted text-xs">created {fmtDate(license.createdAt)}</span>
            </div>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="flex items-center justify-between border-b border-[#2a2f3a] px-4 py-3">
          <h2 className="font-bold">Computers ({license.systems.length} of {license.maxSeats})</h2>
          <span className="muted text-xs">Online = checked in within the last 10 minutes</span>
        </div>
        {license.systems.length === 0 ? (
          <p className="muted px-4 py-6 text-sm">No computer has activated this key yet.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Computer</th><th>ID</th><th>Version</th><th>Last seen</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {license.systems.map((s) => {
                const online = isOnline(s.lastSeenAt);
                return (
                  <tr key={s.id}>
                    <td>
                      <div className="font-semibold">{s.hostname ?? "—"}</div>
                      <div className="muted text-xs">{s.os ?? ""}{s.ip ? ` · ${s.ip}` : ""}</div>
                    </td>
                    <td className="mono text-xs">{s.machineId}</td>
                    <td>{s.appVersion ?? "—"}</td>
                    <td>
                      <Badge status={online ? "online" : "offline"} />
                      <div className="muted mt-1 text-xs">{timeAgo(s.lastSeenAt)} · first {fmtDay(s.firstSeenAt)}</div>
                    </td>
                    <td>
                      <Badge status={s.status} />
                      {s.status === "locked" && s.lockMessage && <div className="mt-1 text-xs text-[#fca5a5]">{s.lockMessage}</div>}
                    </td>
                    <td>
                      <form method="post" action={`/api/admin/systems/${s.id}`} className="flex flex-wrap items-center gap-1">
                        {s.status === "active" ? (
                          <>
                            <input name="message" placeholder="message (optional)" className="w-40 text-xs" />
                            <button className="btn btn-danger btn-small" name="action" value="lock">Lock</button>
                          </>
                        ) : (
                          <button className="btn btn-primary btn-small" name="action" value="unlock">Unlock</button>
                        )}
                        <ConfirmButton message={`Remove ${s.hostname ?? s.machineId}? It will have to activate again and the seat becomes free.`}>
                          <input type="hidden" name="action" value="remove" />Remove
                        </ConfirmButton>
                      </form>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="border-b border-[#2a2f3a] px-4 py-3"><h2 className="font-bold">Activity</h2></div>
        {license.events.length === 0 ? (
          <p className="muted px-4 py-6 text-sm">Nothing yet.</p>
        ) : (
          <table>
            <tbody>
              {license.events.map((e) => (
                <tr key={e.id}>
                  <td className="muted mono w-44 text-xs">{fmtDate(e.createdAt)}</td>
                  <td className="w-28 font-semibold">{e.kind}</td>
                  <td>{e.detail}</td>
                  <td className="muted mono text-xs">{e.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel p-4">
        <h2 className="mb-2 font-bold text-[#fca5a5]">Delete</h2>
        <p className="muted mb-3 text-sm">Deletes the licence and its computers. Prefer Revoke, which keeps the history.</p>
        <form method="post" action={action}>
          <ConfirmButton className="btn btn-danger" message={`Delete licence ${license.key} and its ${license.systems.length} computer(s)? This cannot be undone.`}>
            <input type="hidden" name="action" value="delete" />Delete licence
          </ConfirmButton>
        </form>
      </section>
    </div>
  );
}
