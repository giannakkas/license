import Link from "next/link";
import { prisma } from "@/lib/db";
import { fmtDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function EventsPage() {
  const events = await prisma.event.findMany({ orderBy: { createdAt: "desc" }, take: 300, include: { license: { select: { id: true, label: true, key: true } } } });
  return (
    <section className="panel">
      <div className="border-b border-[#2a2f3a] px-4 py-3"><h1 className="font-bold">Activity (last 300)</h1></div>
      <table>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="muted mono w-44 text-xs">{fmtDate(e.createdAt)}</td>
              <td className="w-28 font-semibold">{e.kind}</td>
              <td>{e.license ? <Link href={`/licenses/${e.license.id}`} className="hover:underline">{e.license.label}</Link> : <span className="muted">—</span>}</td>
              <td>{e.detail}</td>
              <td className="muted mono text-xs">{e.ip}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
