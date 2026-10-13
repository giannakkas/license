import Link from "next/link";
import { Badge } from "@/components/badge";
import { ExtendForm } from "@/components/extend-form";
import { fmtDay, isExpired, timeAgo } from "@/lib/format";
import { isOnline } from "@/lib/licensing";
import { effectiveStatus, latestSeen } from "@/lib/stats";

export type LicenseRow = {
  id: string;
  key: string;
  label: string | null;
  status: string;
  maxSeats: number;
  expiresAt: Date | null;
  product: { id: string; name: string };
  customer: { id: string; name: string };
  systems: { status: string; lastSeenAt: Date; mode?: string }[];
};

/** The licence list used on the dashboard and on the customer and software pages. */
export function LicenseTable({
  licenses,
  back,
  showCustomer = true,
  showProduct = true,
  empty = "No licences yet.",
}: {
  licenses: LicenseRow[];
  /** The page to return to after an Extend. */
  back: string;
  showCustomer?: boolean;
  showProduct?: boolean;
  empty?: string;
}) {
  if (licenses.length === 0) return <p className="muted px-4 py-6 text-sm">{empty}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Key</th>
          {showCustomer && <th>Customer</th>}
          {showProduct && <th>Software</th>}
          <th>Status</th>
          <th>Computers</th>
          <th>Last seen</th>
          <th>Expires</th>
        </tr>
      </thead>
      <tbody>
        {licenses.map((l) => {
          const last = latestSeen(l.systems);
          const lockedSystems = l.systems.filter((s) => s.status === "locked").length;
          const files = l.systems.filter((s) => s.mode === "offline").length;
          const expired = isExpired(l.expiresAt);
          return (
            <tr key={l.id}>
              <td>
                <Link href={`/licenses/${l.id}`} className="mono font-semibold hover:underline">{l.key}</Link>
                {!showCustomer && l.label && <div className="muted text-xs">{l.label}</div>}
              </td>
              {showCustomer && (
                <td>
                  <Link href={`/customers/${l.customer.id}`} className="text-[#93c5fd] hover:underline">{l.customer.name}</Link>
                  {l.label && <div className="muted text-xs">{l.label}</div>}
                </td>
              )}
              {showProduct && (
                <td><Link href={`/products/${l.product.id}`} className="text-[#93c5fd] hover:underline">{l.product.name}</Link></td>
              )}
              <td><Badge status={effectiveStatus(l)} /></td>
              <td>
                {l.systems.length} / {l.maxSeats}
                {lockedSystems > 0 && <span className="ml-2 text-xs text-[#fca5a5]">{lockedSystems} locked</span>}
                {files > 0 && <span className="ml-2 text-xs text-[#93c5fd]">{files} offline file{files === 1 ? "" : "s"}</span>}
              </td>
              <td className={last && isOnline(last) ? "text-[#4ade80]" : "muted"}>{timeAgo(last)}</td>
              <td>
                <div className={expired ? "text-[#fcd34d]" : "muted"}>{l.expiresAt ? fmtDay(l.expiresAt) : "never"}</div>
                {l.status !== "revoked" && <div className="mt-1"><ExtendForm licenseId={l.id} back={back} /></div>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
