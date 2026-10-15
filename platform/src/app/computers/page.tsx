import Link from "next/link";
import { ComputerTable } from "@/components/computer-table";
import { VersionSummary } from "@/components/version-summary";
import type { SystemWhereInput } from "@/generated/prisma/models";
import { loadComputers, versionState, versionSummary } from "@/lib/computers";
import { prisma } from "@/lib/db";
import { isOnline, onlineCutoff } from "@/lib/licensing";

export const dynamic = "force-dynamic";

type Query = { customer?: string; product?: string; version?: string; state?: string; q?: string };

const STATES = [
  ["", "Any state"],
  ["online", "Online now"],
  ["offline", "Offline"],
  ["outdated", "Update waiting"],
  ["locked", "Locked"],
  ["file", "Offline licence file"],
] as const;

export default async function ComputersPage({ searchParams }: { searchParams: Promise<Query> }) {
  const { customer = "", product = "", version = "", state = "", q = "" } = await searchParams;
  const where: SystemWhereInput = {
    ...(customer ? { license: { customerId: customer } } : {}),
    ...(product ? { license: { product: { slug: product }, ...(customer ? { customerId: customer } : {}) } } : {}),
    ...(version ? { appVersion: version } : {}),
    ...(state === "locked" ? { status: "locked" } : {}),
    ...(state === "file" ? { mode: "offline" } : {}),
    ...(state === "online" ? { lastSeenAt: { gte: onlineCutoff() } } : {}),
    ...(state === "offline" ? { lastSeenAt: { lt: onlineCutoff() } } : {}),
    ...(q ? { OR: [{ hostname: { contains: q, mode: "insensitive" } }, { machineId: { contains: q.toUpperCase() } }, { ip: { contains: q } }] } : {}),
  };
  const [rows, customers, products, versions] = await Promise.all([
    loadComputers(where),
    prisma.customer.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
    prisma.product.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true, slug: true } }),
    prisma.system.findMany({ distinct: ["appVersion"], select: { appVersion: true }, where: { appVersion: { not: null } } }),
  ]);
  const computers = state === "outdated" ? rows.filter((c) => ["outdated", "required"].includes(versionState(c))) : rows;
  const online = computers.filter((c) => isOnline(c.lastSeenAt)).length;
  const filtered = Boolean(customer || product || version || state || q);
  const query = new URLSearchParams({ ...(customer && { customer }), ...(product && { product }), ...(version && { version }), ...(state && { state }), ...(q && { q }) }).toString();
  const back = query ? `/computers?${query}` : "/computers";
  const versionList = versions.map((v) => v.appVersion as string).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));

  return (
    <div className="flex flex-col gap-6">
      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="font-bold">Versions in use</h1>
          <span className="muted text-xs">green = newest build · amber = update waiting · red = below the required minimum</span>
        </div>
        <VersionSummary groups={versionSummary(computers)} />
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2a2f3a] px-4 py-3">
          <h2 className="font-bold">
            Computers <span className="muted font-normal">{`· ${computers.length} listed, ${online} online`}</span>
          </h2>
          <form method="get" action="/computers" className="flex flex-wrap items-center gap-2 text-sm">
            <input name="q" defaultValue={q} placeholder="Name, ID or IP" className="w-40" />
            <select name="customer" defaultValue={customer} aria-label="Customer">
              <option value="">All customers</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select name="product" defaultValue={product} aria-label="Software">
              <option value="">All software</option>
              {products.map((p) => <option key={p.id} value={p.slug}>{p.name}</option>)}
            </select>
            <select name="version" defaultValue={version} aria-label="Version">
              <option value="">Any version</option>
              {versionList.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <select name="state" defaultValue={state} aria-label="State">
              {STATES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <button type="submit" className="btn btn-small">Filter</button>
            {filtered && <Link href="/computers" className="btn btn-small">Clear</Link>}
          </form>
        </div>
        <ComputerTable computers={computers} back={back} empty={filtered ? "No computers match these filters." : "No computer has activated yet."} />
      </section>
    </div>
  );
}
