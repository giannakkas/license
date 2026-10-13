import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfirmButton } from "@/components/confirm-button";
import { ErrorBox } from "@/components/error-box";
import { NewLicenseForm } from "@/components/license-form";
import { LicenseTable } from "@/components/license-table";
import { prisma } from "@/lib/db";
import { fmtDate } from "@/lib/format";
import { summarise } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  const [product, products, customers] = await Promise.all([
    prisma.product.findUnique({
      where: { id },
      include: {
        licenses: {
          orderBy: { createdAt: "desc" },
          include: {
            systems: { select: { status: true, lastSeenAt: true } },
            product: { select: { id: true, name: true } },
            customer: { select: { id: true, name: true } },
          },
        },
      },
    }),
    prisma.product.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
    prisma.customer.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
  ]);
  if (!product) notFound();
  const s = summarise(product.licenses);
  const action = `/api/admin/products/${product.id}`;

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

      <section className="panel">
        <div className="border-b border-[#2a2f3a] px-4 py-3"><h2 className="font-bold">Licences</h2></div>
        <LicenseTable licenses={product.licenses} showProduct={false} empty="No licences for this software yet." />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">New licence for {product.name}</h2>
          <NewLicenseForm products={products} customers={customers} productId={product.id} />
        </div>
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">Details</h2>
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
