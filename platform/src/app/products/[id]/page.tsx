import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfirmButton } from "@/components/confirm-button";
import { ErrorBox } from "@/components/error-box";
import { NewLicenseForm } from "@/components/license-form";
import { LicenseTable } from "@/components/license-table";
import { NoticeBox } from "@/components/notice-box";
import { ReleaseUpload } from "@/components/release-upload";
import { prisma } from "@/lib/db";
import { fmtDate, fmtDay } from "@/lib/format";
import { fmtSize } from "@/lib/releases";
import { summarise } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; notice?: string }>;
}) {
  const { id } = await params;
  const { error, notice } = await searchParams;
  const [product, products, customers] = await Promise.all([
    prisma.product.findUnique({
      where: { id },
      include: {
        licenses: {
          orderBy: { createdAt: "desc" },
          include: {
            systems: { select: { status: true, lastSeenAt: true, mode: true } },
            product: { select: { id: true, name: true } },
            customer: { select: { id: true, name: true } },
          },
        },
        releases: { orderBy: { createdAt: "desc" } },
      },
    }),
    prisma.product.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
    prisma.customer.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
  ]);
  if (!product) notFound();
  const s = summarise(product.licenses);
  const action = `/api/admin/products/${product.id}`;
  const publicUrl = (process.env.PUBLIC_URL || "https://player.oncue.cy").replace(/\/$/, "");
  const downloadUrl = `${publicUrl}/download/${product.slug}`;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/products" className="muted text-sm hover:underline">← Software</Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold">{product.name}</h1>
          <code className="mono rounded border border-[#2a2f3a] bg-[#1e222b] px-2 py-0.5 text-sm select-all">{product.slug}</code>
        </div>
        <p className="muted text-sm">
          {s.licences} licence(s) · {s.computers} computer(s), {s.online} online{s.locked ? ` · ${s.locked} locked` : ""}
        </p>
      </div>

      <ErrorBox message={error} />
      <NoticeBox message={notice} />

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2a2f3a] px-4 py-3">
          <h2 className="font-bold">Downloads</h2>
          {product.releases.length > 0 && (
            <span className="muted text-xs">
              Give customers this link (always the latest build): <a href={downloadUrl} className="mono text-[#93c5fd] hover:underline">{downloadUrl}</a>
            </span>
          )}
        </div>
        {product.releases.length === 0 ? (
          <p className="muted px-4 py-3 text-sm">No build uploaded yet. Once one is, customers download it from <span className="mono">{downloadUrl}</span>.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Version</th><th>File</th><th>Size</th><th>SHA-256</th><th>Uploaded</th><th>Downloads</th><th></th></tr>
            </thead>
            <tbody>
              {product.releases.map((r, i) => (
                <tr key={r.id}>
                  <td>
                    <span className="font-semibold">{r.version}</span>
                    {i === 0 && <span className="ml-2 rounded border border-[#1f5a35] bg-[#14301f] px-1.5 text-[10px] font-bold uppercase text-[#4ade80]">latest</span>}
                    {r.notes && <div className="muted text-xs">{r.notes}</div>}
                  </td>
                  <td><a href={`/download/${product.slug}/${r.id}`} className="mono text-xs text-[#93c5fd] hover:underline">{r.filename}</a></td>
                  <td className="muted text-xs">{fmtSize(r.size)}</td>
                  <td className="mono muted text-xs" title={r.sha256}>{r.sha256.slice(0, 12)}…</td>
                  <td className="muted text-xs">{fmtDay(r.createdAt)}</td>
                  <td>{r.downloads}</td>
                  <td className="text-right">
                    <form method="post" action={`/api/admin/releases/${r.id}`}>
                      <ConfirmButton className="btn btn-danger btn-small" message={`Delete build ${r.version} (${r.filename})?`}>
                        <input type="hidden" name="action" value="delete" />Delete
                      </ConfirmButton>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="border-t border-[#2a2f3a] p-4">
          <h3 className="mb-2 text-sm font-bold">Upload a build</h3>
          <ReleaseUpload productId={product.id} />
        </div>
      </section>

      <section className="panel">
        <div className="border-b border-[#2a2f3a] px-4 py-3"><h2 className="font-bold">Licences</h2></div>
        <LicenseTable licenses={product.licenses} back={`/products/${product.id}`} showProduct={false} empty="No licences for this software yet." />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">New licence for {product.name}</h2>
          <NewLicenseForm products={products} customers={customers} productId={product.id} />
        </div>
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">Edit software</h2>
          <form method="post" action={action} className="grid gap-2 text-sm">
            <input type="hidden" name="action" value="update" />
            <label className="flex flex-col gap-1">Name<input name="name" defaultValue={product.name} required /></label>
            <label className="flex flex-col gap-1">
              Slug
              <input name="slug" defaultValue={product.slug} required pattern="[a-z0-9][a-z0-9-]+" />
              <span className="muted text-xs">Programs built with the old slug are refused after a change.</span>
            </label>
            <label className="flex flex-col gap-1">Notes<textarea name="notes" rows={3} defaultValue={product.notes ?? ""} /></label>
            <div className="flex items-center justify-between">
              <button type="submit" className="btn">Save</button>
              <span className="muted text-xs">since {fmtDate(product.createdAt)}</span>
            </div>
          </form>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="mb-2 font-bold">Integration</h2>
        <p className="muted mb-2 text-sm">The program activates, checks in and deactivates with this body (plus its activation token after the first call):</p>
        <pre className="mono overflow-x-auto rounded border border-[#2a2f3a] bg-[#1e222b] p-3 text-xs">{`POST /api/v1/activate
{"key": "ONCUE-XXXXX-XXXXX-XXXXX-XXXXX", "machine_id": "<stable id>", "hostname": "...", "os": "...", "version": "...", "product": "${product.slug}"}`}</pre>
        <p className="muted mt-2 text-sm">
          For computers without internet the program verifies offline licence files with the platform&apos;s public key, published at{" "}
          <a href="/api/v1/public-key" className="mono text-[#93c5fd] hover:underline">/api/v1/public-key</a> (RSASSA-PKCS1-v1_5, SHA-256 over the file&apos;s payload).
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-2 font-bold text-[#fca5a5]">Delete</h2>
        {product.licenses.length > 0 ? (
          <p className="muted text-sm">This software has licences. Delete them, or move them to another software, first.</p>
        ) : (
          <form method="post" action={action}>
            <ConfirmButton className="btn btn-danger" message={`Delete software ${product.name}?`}>
              <input type="hidden" name="action" value="delete" />Delete software
            </ConfirmButton>
          </form>
        )}
      </section>
    </div>
  );
}
