import Link from "next/link";
import { Sparkles } from "lucide-react";

export default function Home() {
  return (
    <main className="grid-bg flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      <div className="flex items-center gap-3">
        <Sparkles className="h-8 w-8 text-mint" />
        <h1 className="text-4xl font-bold tracking-tight">Autogent</h1>
      </div>
      <p className="max-w-md text-center text-lg text-ink/60">
        An agentic execution platform. One backend owns the agent loop, tools,
        and memory. The agent calls tools to do real work.
      </p>
      <div className="flex gap-4">
        <Link
          href="/login"
          className="rounded-lg bg-mint px-6 py-3 font-medium text-canvas transition hover:brightness-110"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="rounded-lg border border-line px-6 py-3 font-medium transition hover:border-mint/50"
        >
          Get started
        </Link>
      </div>
    </main>
  );
}
