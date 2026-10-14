import Link from "next/link";
import { notFound } from "next/navigation";
import { AutoDownload } from "@/components/auto-download";
import { Badge } from "@/components/badge";
import { ConfirmButton } from "@/components/confirm-button";
import { ErrorBox } from "@/components/error-box";
import { ExtendForm } from "@/components/extend-form";
import { NoticeBox } from "@/components/notice-box";
import { prisma } from "@/lib/db";
import { fmtDate, fmtDay, timeAgo } from "@/lib/format";
import { addMonths } from "@/lib/forms";
import { isOnline } from "@/lib/licensing";
import { offlineFilesConfigured } from "@/lib/offline";
import { isNewer } from "@/lib/catalog";
import { effectiveStatus } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function LicensePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; notice?: string; download?: string }>;
}) {
  const { id } = await params;
  const { error, notice, download } = await searchParams;
  const [license, products, customers] = await Promise.all([
    prisma.license.findUnique({
      where: { id },
      include: {
        product: { select: { id: true, name: true, slug: true, minVersion: true, releases: { orderBy: { createdAt: "desc" }, take: 1, select: { version: true } } } },
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
  const back = `/licenses/${license.id}`;
  const latestVersion = license.product.releases[0]?.version ?? null;
  const filesOn = offlineFilesConfigured();
  const defaultFileExpiry = fmtDay(license.expiresAt && license.expiresAt > new Date() ? license.expiresAt : addMonths(new Date(), 12));

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
          <span className="muted text-sm">expires {license.expiresAt ? fmtDay(license.expiresAt) : "never"}</span>
          {license.status !== "revoked" && <ExtendForm licenseId={license.id} back={back} />}
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
      <NoticeBox message={notice} />
      {download && <AutoDownload url={`/api/admin/systems/${download}/file`} />}

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

      <section className="panel p-4">
        <h2 className="mb-1 font-bold">Offline licence file</h2>
        <p className="muted mb-3 text-sm">
          For a computer with no internet. The program shows a 20-character computer ID on its activation screen (Copy ID):
          enter it here, choose until when the file is valid, and give the downloaded <span className="mono">.lic</span> file to
          the operator to import. The file works on that computer only and takes one of the licence&apos;s seats; to extend it,
          extend the licence and download the file again.
        </p>
        {filesOn ? (
          license.status === "revoked" ? (
            <p className="muted text-sm">The licence is revoked; reinstate it to issue files.</p>
          ) : (
            <form method="post" action={action} className="grid gap-3 md:grid-cols-[2fr_2fr_1fr_auto]">
              <input type="hidden" name="action" value="offline" />
              <label className="flex flex-col gap-1 text-sm">
                Computer ID
                <input name="machineId" required minLength={20} placeholder="ABCDE12345FGHIJ67890" className="mono" />
              </label>
              <label className="flex flex-col gap-1 text-sm">Computer name (optional)<input name="hostname" placeholder="e.g. MCR-PC-2" /></label>
              <label className="flex flex-col gap-1 text-sm">Valid until<input name="expiresAt" type="date" required defaultValue={defaultFileExpiry} /></label>
              <div className="flex items-end"><button type="submit" className="btn btn-primary">Issue file</button></div>
            </form>
          )
        ) : (
          <p className="text-sm text-[#fcd34d]">Not configured on this platform: set LICENSE_FILE_PRIVATE_KEY (see the README).</p>
        )}
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
              <tr><th>Computer</th><th>ID</th><th>Version</th><th>Licence</th><th>Last seen</th><th>Status</th><th>Actions</th></tr>
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
                    <td>
                      {s.appVersion ?? "—"}
                      {latestVersion && s.appVersion && isNewer(latestVersion, s.appVersion) && (
                        <div className={`text-xs ${license.product.minVersion && isNewer(license.product.minVersion, s.appVersion) ? "text-[#fca5a5]" : "text-[#fcd34d]"}`}>
                          {`${latestVersion} available`}
                        </div>
                      )}
                    </td>
                    <td>
                      {s.mode === "offline" ? (
                        <>
                          <Badge status="file" label="offline file" />
                          <div className="muted mt-1 text-xs">
                            valid until {fmtDay(s.offlineExpiresAt)} ·{" "}
                            <a href={`/api/admin/systems/${s.id}/file`} className="text-[#93c5fd] hover:underline">Download file</a>
                          </div>
                        </>
                      ) : (
                        <Badge status="offline" label="online key" />
                      )}
                    </td>
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
