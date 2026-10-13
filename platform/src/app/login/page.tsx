export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const { error, next } = await searchParams;
  return (
    <div className="mx-auto mt-16 max-w-sm">
      <div className="panel p-6">
        <h1 className="mb-1 text-lg font-bold">Sign in</h1>
        <p className="muted mb-4 text-sm">Serial keys, customers and remote lock for your software.</p>
        <form method="post" action="/api/auth/login" className="flex flex-col gap-3">
          <input type="hidden" name="next" value={next ?? "/"} />
          <label className="flex flex-col gap-1 text-sm">
            Password
            <input type="password" name="password" autoFocus required autoComplete="current-password" />
          </label>
          {error && <p className="text-sm text-[#fca5a5]">{error}</p>}
          <button type="submit" className="btn btn-primary justify-center">Sign in</button>
        </form>
      </div>
    </div>
  );
}
