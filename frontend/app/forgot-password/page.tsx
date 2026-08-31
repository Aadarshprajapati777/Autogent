"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Sparkles, Mail, ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid-bg flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-sm space-y-6">
        <Link
          href="/login"
          className="flex items-center gap-1.5 text-sm text-zinc-500 transition hover:text-zinc-300"
        >
          <ArrowLeft size={14} /> Back to sign in
        </Link>

        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-mint/10">
            <Sparkles className="h-5 w-5 text-mint" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Reset password</h1>
            <p className="text-sm text-zinc-500">We&apos;ll email you a reset link</p>
          </div>
        </div>

        {sent ? (
          <div className="space-y-4 rounded-xl border border-mint/20 bg-mint/5 p-5">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-mint" />
              <p className="font-medium text-mint">Check your inbox</p>
            </div>
            <p className="text-sm text-zinc-400">
              If an account exists for <span className="font-medium text-zinc-200">{email}</span>,
              you&apos;ll receive a password reset link shortly. The link expires in 1 hour.
            </p>
            <Link
              href="/login"
              className="block w-full rounded-lg bg-mint py-2.5 text-center font-medium text-canvas transition hover:brightness-110"
            >
              Back to sign in
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm text-zinc-400">Email</label>
              <div className="relative">
                <Mail
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600"
                />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full rounded-lg border border-line bg-panel pl-9 pr-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
                  placeholder="you@example.com"
                />
              </div>
            </div>
            {error && (
              <p className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-sm text-rose-400">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-mint px-4 py-2.5 font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Sending...
                </>
              ) : (
                "Send reset link"
              )}
            </button>
          </form>
        )}

        <p className="text-center text-sm text-zinc-500">
          New to Autogent?{" "}
          <Link href="/signup" className="text-mint hover:underline">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}
