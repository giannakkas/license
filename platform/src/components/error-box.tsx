export function ErrorBox({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="rounded border border-[#7a2323] bg-[#3a1416] px-3 py-2 text-sm text-[#fca5a5]">{message}</p>;
}
