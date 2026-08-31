"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCcw, Home } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="grid-bg flex min-h-screen flex-col items-center justify-center p-8">
      <div className="flex max-w-md flex-col items-center text-center">
        <div className="grid h-16 w-16 place-items-center rounded-2xl bg-rose-500/10">
          <AlertTriangle className="h-8 w-8 text-rose-400" />
        </div>
        <h1 className="mt-6 text-3xl font-bold">Something went wrong</h1>
        <p className="mt-2 text-zinc-500">
          An unexpected error occurred while rendering this page. Our team has been notified.
        </p>
        {error.digest && (
          <p className="mt-3 rounded-md border border-line bg-panel px-3 py-1.5 font-mono text-xs text-zinc-600">
            Error ID: {error.digest}
          </p>
        )}
        <div className="mt-6 flex gap-3">
          <button
            onClick={reset}
            className="flex items-center gap-2 rounded-lg bg-mint px-5 py-2.5 font-medium text-canvas transition hover:brightness-110"
          >
            <RotateCcw size={16} /> Try again
          </button>
          <Link
            href="/"
            className="flex items-center gap-2 rounded-lg border border-line px-5 py-2.5 font-medium transition hover:border-mint/50"
          >
            <Home size={16} /> Home
          </Link>
        </div>
      </div>
    </div>
  );
}
