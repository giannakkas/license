import Link from "next/link";

type Option = { id: string; name: string };

/** The "new licence" form. Preselect a software or a customer when the page is about one. */
export function NewLicenseForm({
  products,
  customers,
  productId,
  customerId,
}: {
  products: Option[];
  customers: Option[];
  productId?: string;
  customerId?: string;
}) {
  if (products.length === 0) {
    return (
      <p className="muted text-sm">
        Add a software under <Link href="/products" className="underline">Software</Link> before creating keys.
      </p>
    );
  }
  return (
    <form method="post" action="/api/admin/licenses" className="grid gap-3 md:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm">
        Software
        <select name="productId" defaultValue={productId ?? products[0].id} required>
          {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Customer
        <select name="customerId" defaultValue={customerId ?? ""}>
          <option value="">New customer (type the name below)</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      {!customerId && (
        <label className="flex flex-col gap-1 text-sm">
          New customer name
          <input name="customerName" placeholder="Company, studio or person" />
        </label>
      )}
      <label className="flex flex-col gap-1 text-sm">
        Reference (optional)
        <input name="label" placeholder="Site, studio, invoice number" />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Computers allowed
        <input name="maxSeats" type="number" min={1} max={500} defaultValue={1} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Expires (optional)
        <input name="expiresAt" type="date" />
      </label>
      <label className="flex flex-col gap-1 text-sm md:col-span-2">
        Notes (optional)
        <input name="notes" placeholder="Anything useful" />
      </label>
      <div className="md:col-span-2">
        <button type="submit" className="btn btn-primary">Create key</button>
      </div>
    </form>
  );
}
