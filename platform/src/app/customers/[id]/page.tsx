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

export default async function CustomerPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  const [customer, products, customers] = await Promise.all([
    prisma.customer.findUnique({
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
  if (!customer) notFound();
  const s = summarise(customer.licenses);
  const action = `/api/admin/customers/${customer.id}`;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/customers" className="muted text-sm hover:underline">← Customers</Link>
        <h1 className="mt-2 text-xl font-bold">{customer.name}</h1>
        <p className="muted text-sm">
          {s.licences} licence(s) · {s.computers} computer(s), {s.online} online{s.locked ? ` · ${s.locked} locked` : ""}
          {customer.email ? ` · ${customer.email}` : ""}{customer.phone ? ` · ${customer.phone}` : ""}
        </p>
      </div>

      <ErrorBox message={error} />

      <section className="panel">
        <div className="border-b border-[#2a2f3a] px-4 py-3"><h2 className="font-bold">Licences</h2></div>
        <LicenseTable licenses={customer.licenses} showCustomer={false} empty="No licences for this customer yet." />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">New licence for {customer.name}</h2>
          <NewLicenseForm products={products} customers={customers} customerId={customer.id} />
        </div>
        <div className="panel p-4">
          <h2 className="mb-3 font-bold">Edit customer</h2>
          <form method="post" action={action} className="grid gap-2 text-sm">
            <input type="hidden" name="action" value="update" />
            <label className="flex flex-col gap-1">Name<input name="name" defaultValue={customer.name} required /></label>
            <label className="flex flex-col gap-1">Email<input name="email" type="email" defaultValue={customer.email ?? ""} /></label>
            <label className="flex flex-col gap-1">Phone<input name="phone" defaultValue={customer.phone ?? ""} /></label>
            <label className="flex flex-col gap-1">Notes<textarea name="notes" rows={3} defaultValue={customer.notes ?? ""} /></label>
            <div className="flex items-center justify-between">
              <button type="submit" className="btn">Save</button>
              <span className="muted text-xs">since {fmtDate(customer.createdAt)}</span>
            </div>
          </form>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="mb-2 font-bold text-[#fca5a5]">Delete</h2>
        {customer.licenses.length > 0 ? (
          <p className="muted text-sm">This customer has licences. Delete them, or move them to another customer, first.</p>
        ) : (
          <form method="post" action={action}>
            <ConfirmButton className="btn btn-danger" message={`Delete customer ${customer.name}?`}>
              <input type="hidden" name="action" value="delete" />Delete customer
            </ConfirmButton>
          </form>
        )}
      </section>
    </div>
  );
}
