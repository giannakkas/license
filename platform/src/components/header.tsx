import Image from "next/image";
import Link from "next/link";
import { cookies } from "next/headers";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

export async function Header() {
  const signedIn = await verifySessionToken((await cookies()).get(SESSION_COOKIE)?.value);
  return (
    <header className="border-b border-[#2a2f3a] bg-[#171a21]">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <Link href="/" className="flex items-center gap-3">
          <Image src="/logo.png" alt="" width={37} height={28} priority unoptimized />
          <span className="font-bold">OnCue Licensing</span>
          <span className="muted text-sm">license.oncue.cy</span>
        </Link>
        {signedIn && (
          <nav className="ml-auto flex items-center gap-4 text-sm">
            <Link href="/" className="hover:underline">Licences</Link>
            <Link href="/customers" className="hover:underline">Customers</Link>
            <Link href="/products" className="hover:underline">Software</Link>
            <Link href="/events" className="hover:underline">Activity</Link>
            <form method="post" action="/api/auth/logout">
              <button type="submit" className="btn btn-small">Log out</button>
            </form>
          </nav>
        )}
      </div>
    </header>
  );
}
