import Link from "next/link";
import { ErrorBox } from "@/components/error-box";
import { prisma } from "@/lib/db";
import { timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";
import { latestSeen, summarise } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function ProductsPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const products = await prisma.product.findMany({
    orderBy: { name: "asc" },
    include: {
      licenses: { select: { status: true, expiresAt: true, customerId: true, systems: { select: { status: true, lastSeenAt: true } } } },
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <ErrorBox message={error} />
      <section className="panel">
        <div className="flex items-center justify-between border-b border-[#2a2f3a] px-4 py-3">
          <h1 className="font-bold">Software</h1>
          <span className="muted text-xs">{products.length} total</span>
        </div>
        {products.length === 0 ? (
          <p className="muted px-4 py-6 text-sm">No software registered yet. Add the first one below.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Software</th><th>Slug</th><th>Customers</th><th>Licences</th><th>Computers</th><th>Last seen</th></tr>
            </thead>
            <tbody>
              {products.map((p) => {
                const s = summarise(p.licenses);
                const customers = new Set(p.licenses.map((l) => l.customerId)).size;
                const last = latestSeen(p.licenses.flatMap((l) => l.systems));
                return (
                  <tr key={p.id}>
                    <td><Link href={`/products/${p.id}`} className="font-semibold hover:underline">{p.name}</Link></td>
                    <td className="mono text-xs">{p.slug}</td>
                    <td>{customers}</td>
                    <td>
                      {s.licences}
                      {s.locked > 0 && <span className="ml-2 text-xs text-[#fca5a5]">{s.locked} locked</span>}
                    </td>
                    <td>
                      {s.computers}
                      {s.online > 0 && <span className="ml-2 text-xs text-[#4ade80]">{s.online} online</span>}
                    </td>
                    <td className={last && isOnline(last) ? "text-[#4ade80]" : "muted"}>{timeAgo(last)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel p-4">
        <h2 className="mb-1 font-bold">New software</h2>
        <p className="muted mb-3 text-sm">
          Each program sends its slug as <span className="mono">product</span> when it activates, so a key for one software
          cannot be used by another. The slug is derived from the name unless you set it.
        </p>
        <form method="post" action="/api/admin/products" className="grid gap-3 md:grid-cols-[2fr_1fr_auto]">
          <label className="flex flex-col gap-1 text-sm">Name<input name="name" required placeholder="e.g. Playout Server" /></label>
          <label className="flex flex-col gap-1 text-sm">Slug (optional)<input name="slug" placeholder="playout-server" /></label>
          <div className="flex items-end"><button type="submit" className="btn btn-primary">Add software</button></div>
          <label className="flex flex-col gap-1 text-sm md:col-span-3">Notes (optional)<input name="notes" /></label>
        </form>
      </section>
    </div>
  );
}
