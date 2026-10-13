export function NoticeBox({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="rounded border border-[#1f5a35] bg-[#14301f] px-3 py-2 text-sm text-[#4ade80]">{message}</p>;
}
