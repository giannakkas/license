const COLORS: Record<string, string> = {
  active: "bg-[#14301f] text-[#4ade80] border-[#1f5a35]",
  online: "bg-[#14301f] text-[#4ade80] border-[#1f5a35]",
  locked: "bg-[#3a1416] text-[#fca5a5] border-[#7a2323]",
  revoked: "bg-[#3a1416] text-[#fca5a5] border-[#7a2323]",
  expired: "bg-[#3a2a10] text-[#fcd34d] border-[#7a5a1a]",
  offline: "bg-[#1e222b] text-[#8b93a3] border-[#2a2f3a]",
  file: "bg-[#172554] text-[#93c5fd] border-[#1e3a8a]",
};

export function Badge({ status, label }: { status: string; label?: string }) {
  const cls = COLORS[status] ?? COLORS.offline;
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${cls}`}>
      {label ?? status}
    </span>
  );
}
