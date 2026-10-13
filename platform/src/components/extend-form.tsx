/** Pushes a licence's expiry out by a few months; `back` is where to return to afterwards. */
export function ExtendForm({ licenseId, back }: { licenseId: string; back: string }) {
  return (
    <form method="post" action={`/api/admin/licenses/${licenseId}`} className="flex items-center gap-1">
      <input type="hidden" name="action" value="extend" />
      <input type="hidden" name="back" value={back} />
      <select name="months" defaultValue="12" aria-label="Extend by" className="py-0.5 text-xs">
        <option value="1">+1 month</option>
        <option value="3">+3 months</option>
        <option value="6">+6 months</option>
        <option value="12">+1 year</option>
      </select>
      <button type="submit" className="btn btn-small">Extend</button>
    </form>
  );
}
