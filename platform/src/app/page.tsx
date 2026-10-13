import Link from "next/link";
import { ErrorBox } from "@/components/error-box";
import { NoticeBox } from "@/components/notice-box";
import { NewLicenseForm } from "@/components/license-form";
import { LicenseTable } from "@/components/license-table";
import { prisma } from "@/lib/db";
import type { Prisma } from "@/generated/prisma/client";
import { summarise } from "@/lib/stats";

export const dynamic = "force-dynamic";

type Query = { error?: string; notice?: string; product?: string; customer?: string; status?: string };

const STATUSES = ["active", "locked", "revoked", "expired"] as const;

export default async function Dashboard({ searchParams }: { searchParams: Promise<Query> }) {
  const { error, notice, product = "", customer = "", status = "" } = await searchParams;
  const now = new Date();
  const where: Prisma.LicenseWhereInput = {
    ...(product ? { product: { slug: product } } : {}),
    ...(customer ? { customerId: customer } : {}),
    ...(status === "active" ? { status: "active", OR: [{ expiresAt: null }, { expiresAt: { gte: now } }] } : {}),
    ...(status === "expired" ? { status: "active", expiresAt: { lt: now } } : {}),
    ...(status === "locked" || status === "revoked" ? { status } : {}),
  };
  const [products, customers, licenses] = await Promise.all([
    prisma.product.findMany({ orderBy: { name: "asc" } }),
    prisma.customer.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
    prisma.license.findMany({
      where,
      orderBy: { createdAt: "desc" },
      include: {
        systems: { select: { status: true, lastSeenAt: true, mode: true } },
        product: { select: { id: true, name: true } },
        customer: { select: { id: true, name: true } },
      },
    }),
  ]);
  const s = summarise(licenses);
  const filtered = Boolean(product || customer || status);
  const query = new URLSearchParams({ ...(product && { product }), ...(customer && { customer }), ...(status && { status }) }).toString();
  const back = query ? `/?${query}` : "/";
  const selectedProduct = products.find((p) => p.slug === product);
  const selectedCustomer = customers.find((c) => c.id === customer);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Licences" value={s.licences} />
        <Stat label="Computers online" value={s.online} hint={`of ${s.computers}${s.files ? `, ${s.files} offline file${s.files === 1 ? "" : "s"}` : ""}`} />
        <Stat label="Locked" value={s.locked} tone={s.locked ? "red" : undefined} />
        <Stat label="Revoked / expired" value={s.revoked + s.expired} />
      </div>

      <ErrorBox message={error} />
      <NoticeBox message={notice} />

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2a2f3a] px-4 py-3">
          <h2 className="font-bold">
            Licences
            {selectedProduct && <span className="muted font-normal"> · {selectedProduct.name}</span>}
            {selectedCustomer && <span className="muted font-normal"> · {selectedCustomer.name}</span>}
          </h2>
          <form method="get" action="/" className="flex flex-wrap items-center gap-2 text-sm">
            <select name="product" defaultValue={product} aria-label="Software">
              <option value="">All software</option>
              {products.map((p) => <option key={p.id} value={p.slug}>{p.name}</option>)}
            </select>
            <select name="customer" defaultValue={customer} aria-label="Customer">
              <option value="">All customers</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select name="status" defaultValue={status} aria-label="Status">
              <option value="">Any status</option>
              {STATUSES.map((st) => <option key={st} value={st}>{st}</option>)}
            </select>
            <button type="submit" className="btn btn-small">Filter</button>
            {filtered && <Link href="/" className="btn btn-small">Clear</Link>}
          </form>
        </div>
        <LicenseTable
          licenses={licenses}
          back={back}
          empty={filtered ? "No licences match these filters." : "No licences yet. Create the first one below."}
        />
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-bold">New licence</h2>
        <NewLicenseForm products={products} customers={customers} productId={selectedProduct?.id} customerId={selectedCustomer?.id} />
      </section>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: number; hint?: string; tone?: "red" }) {
  return (
    <div className="panel px-4 py-3">
      <div className="muted text-xs uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold ${tone === "red" ? "text-[#fca5a5]" : ""}`}>
        {value}
        {hint && <span className="muted ml-2 text-sm font-normal">{hint}</span>}
      </div>
    </div>
  );
}
