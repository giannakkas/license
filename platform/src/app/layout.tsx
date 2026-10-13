import type { Metadata } from "next";
import { Header } from "@/components/header";
import "./globals.css";

export const metadata: Metadata = {
  title: "Monitoring Application — licensing",
  description: "Serial keys, activated computers and remote lock for the Monitoring Application.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <Header />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="muted mx-auto w-full max-w-6xl px-4 py-4 text-xs">
          Programs activate at <span className="mono">POST /api/v1/activate</span> and check in every few minutes; lock a
          licence or a single computer here and it stops within one check-in.
        </footer>
      </body>
    </html>
  );
}
