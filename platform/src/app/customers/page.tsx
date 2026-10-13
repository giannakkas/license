import Link from "next/link";
import { ErrorBox } from "@/components/error-box";
import { prisma } from "@/lib/db";
import { timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";
import { latestSeen, summarise } from "@/lib/stats";

export const dynamic = "force-dynamic";

export default async function CustomersPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const customers = await prisma.customer.findMany({
    orderBy: { name: "asc" },
    include: {
      licenses: {
        select: { status: true, expiresAt: true, product: { select: { name: true } }, systems: { select: { status: true, lastSeenAt: true, mode: true } } },
      },
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <ErrorBox message={error} />
      <section className="panel">
        <div className="flex items-center justify-between border-b border-[#2a2f3a] px-4 py-3">
          <h1 className="font-bold">Customers</h1>
          <span className="muted text-xs">{customers.length} total</span>
        </div>
        {customers.length === 0 ? (
          <p className="muted px-4 py-6 text-sm">No customers yet. Add one below, or create a licence and type a new customer name.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Customer</th><th>Contact</th><th>Software</th><th>Licences</th><th>Computers</th><th>Last seen</th><th></th></tr>
            </thead>
            <tbody>
              {customers.map((c) => {
                const s = summarise(c.licenses);
                const softwares = [...new Set(c.licenses.map((l) => l.product.name))];
                const last = latestSeen(c.licenses.flatMap((l) => l.systems));
                return (
                  <tr key={c.id}>
                    <td><Link href={`/customers/${c.id}`} className="font-semibold text-[#93c5fd] hover:underline">{c.name}</Link></td>
                    <td className="muted text-xs">{[c.email, c.phone].filter(Boolean).join(" · ") || "—"}</td>
                    <td className="text-xs">{softwares.length ? softwares.join(", ") : <span className="muted">—</span>}</td>
                    <td>
                      {s.licences}
                      {s.locked > 0 && <span className="ml-2 text-xs text-[#fca5a5]">{s.locked} locked</span>}
                      {s.revoked + s.expired > 0 && <span className="muted ml-2 text-xs">{s.revoked + s.expired} ended</span>}
                    </td>
                    <td>
                      {s.computers}
                      {s.online > 0 && <span className="ml-2 text-xs text-[#4ade80]">{s.online} online</span>}
                    </td>
                    <td className={last && isOnline(last) ? "text-[#4ade80]" : "muted"}>{timeAgo(last)}</td>
                    <td className="text-right"><Link href={`/customers/${c.id}`} className="btn btn-small">Edit</Link></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-bold">New customer</h2>
        <form method="post" action="/api/admin/customers" className="grid gap-3 md:grid-cols-[2fr_2fr_1fr_auto]">
          <label className="flex flex-col gap-1 text-sm">Name<input name="name" required placeholder="Company, studio or person" /></label>
          <label className="flex flex-col gap-1 text-sm">Email (optional)<input name="email" type="email" /></label>
          <label className="flex flex-col gap-1 text-sm">Phone (optional)<input name="phone" /></label>
          <div className="flex items-end"><button type="submit" className="btn btn-primary">Add customer</button></div>
          <label className="flex flex-col gap-1 text-sm md:col-span-4">Notes (optional)<input name="notes" /></label>
        </form>
      </section>
    </div>
  );
}
