import Link from "next/link";
import { Compass } from "lucide-react";

export default function NotFound() {
  return (
    <div className="grid-bg flex min-h-screen flex-col items-center justify-center p-8">
      <div className="flex max-w-md flex-col items-center text-center">
        <div className="grid h-16 w-16 place-items-center rounded-2xl bg-mint/10">
          <Compass className="h-8 w-8 text-mint" />
        </div>
        <p className="mt-6 text-6xl font-black tracking-tighter text-mint">404</p>
        <h1 className="mt-2 text-2xl font-bold">Page not found</h1>
        <p className="mt-2 text-zinc-500">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>
        <div className="mt-6 flex gap-3">
          <Link
            href="/"
            className="rounded-lg bg-mint px-5 py-2.5 font-medium text-canvas transition hover:brightness-110"
          >
            Back to home
          </Link>
          <Link
            href="/dashboard"
            className="rounded-lg border border-line px-5 py-2.5 font-medium transition hover:border-mint/50"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
