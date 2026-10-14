import type { VersionGroup, VersionState } from "@/lib/computers";

const STATE_CLASS: Record<VersionState, string> = {
  current: "border-[#1f5a35] bg-[#14301f] text-[#4ade80]",
  outdated: "border-[#7a5a1a] bg-[#3a2a10] text-[#fcd34d]",
  required: "border-[#7a2323] bg-[#3a1416] text-[#fca5a5]",
  unknown: "border-[#2a2f3a] bg-[#1e222b] text-[#8b93a3]",
};

/** "Monitoring Application: 1.4.2 ×3 · 1.3.1 ×1" as coloured chips: green = newest, amber = update waiting, red = below minimum. */
export function VersionSummary({ groups, showProduct = true }: { groups: VersionGroup[]; showProduct?: boolean }) {
  if (groups.length === 0) return <p className="muted text-sm">No computer has activated yet.</p>;
  return (
    <div className="flex flex-col gap-2">
      {groups.map((g) => (
        <div key={g.product.id} className="flex flex-wrap items-center gap-2 text-sm">
          {showProduct && <span className="font-semibold">{g.product.name}</span>}
          <span className="muted text-xs">{`${g.total} computer${g.total === 1 ? "" : "s"}${g.latest ? `, newest build ${g.latest}` : ""}`}</span>
          {g.versions.map((v) => (
            <span key={v.version} className={`rounded border px-2 py-0.5 text-xs font-semibold ${STATE_CLASS[v.state]}`} title={v.state}>
              {`${v.version} × ${v.count}`}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}
