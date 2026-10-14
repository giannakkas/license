import Link from "next/link";
import { Badge } from "@/components/badge";
import type { ComputerRow } from "@/lib/computers";
import { versionState } from "@/lib/computers";
import { fmtDay, timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";

/** Every computer of a customer, a software or the whole fleet: name, software, version, licence, state. */
export function ComputerTable({
  computers,
  showCustomer = true,
  showProduct = true,
  empty = "No computers yet.",
}: {
  computers: ComputerRow[];
  showCustomer?: boolean;
  showProduct?: boolean;
  empty?: string;
}) {
  if (computers.length === 0) return <p className="muted px-4 py-6 text-sm">{empty}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Computer</th>
          {showCustomer && <th>Customer</th>}
          {showProduct && <th>Software</th>}
          <th>Version</th>
          <th>Licence</th>
          <th>Status</th>
          <th>Installed</th>
          <th>Last seen</th>
        </tr>
      </thead>
      <tbody>
        {computers.map((c) => {
          const online = isOnline(c.lastSeenAt);
          const state = versionState(c);
          const latest = c.license.product.releases[0]?.version;
          return (
            <tr key={c.id}>
              <td>
                <div className="font-semibold">{c.hostname ?? "—"}</div>
                <div className="muted text-xs">{[c.os, c.ip].filter(Boolean).join(" · ")}</div>
                <div className="muted mono text-[10px]">{c.machineId}</div>
              </td>
              {showCustomer && (
                <td>
                  <Link href={`/customers/${c.license.customer.id}`} className="text-[#93c5fd] hover:underline">{c.license.customer.name}</Link>
                  {c.license.label && <div className="muted text-xs">{c.license.label}</div>}
                </td>
              )}
              {showProduct && (
                <td><Link href={`/products/${c.license.product.id}`} className="text-[#93c5fd] hover:underline">{c.license.product.name}</Link></td>
              )}
              <td>
                <span className="font-semibold">{c.appVersion ?? "—"}</span>
                {state === "outdated" && <div className="text-xs text-[#fcd34d]">{`${latest} available`}</div>}
                {state === "required" && <div className="text-xs text-[#fca5a5]">{`must update to ${latest}`}</div>}
                {state === "current" && <div className="muted text-xs">newest</div>}
              </td>
              <td>
                <Link href={`/licenses/${c.license.id}`} className="mono text-xs text-[#93c5fd] hover:underline">{`…${c.license.key.slice(-5)}`}</Link>
                <div className="muted text-xs">
                  {c.mode === "offline" ? `offline file to ${fmtDay(c.offlineExpiresAt)}` : "online key"}
                </div>
              </td>
              <td>
                <div className="flex flex-wrap gap-1">
                  <Badge status={online ? "online" : "offline"} />
                  {c.status === "locked" && <Badge status="locked" />}
                  {c.license.status !== "active" && <Badge status={c.license.status} label={`licence ${c.license.status}`} />}
                </div>
              </td>
              <td className="muted text-xs">{fmtDay(c.firstSeenAt)}</td>
              <td className={online ? "text-[#4ade80]" : "muted"}>{timeAgo(c.lastSeenAt)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
