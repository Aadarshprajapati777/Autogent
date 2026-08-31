"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Sparkles, Lock, ArrowLeft, CheckCircle2, Loader2, AlertCircle } from "lucide-react";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="grid-bg flex min-h-screen items-center justify-center p-8">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-rose-500/10">
              <AlertCircle className="h-5 w-5 text-rose-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">Invalid link</h1>
              <p className="text-sm text-zinc-500">This reset link is missing a token</p>
            </div>
          </div>
          <p className="text-sm text-zinc-400">
            The reset link you followed doesn&apos;t include a valid token. Please request a new
            password reset link.
          </p>
          <Link
            href="/forgot-password"
            className="block w-full rounded-lg bg-mint py-2.5 text-center font-medium text-canvas transition hover:brightness-110"
          >
            Request new link
          </Link>
        </div>
      </div>
    );
  }

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
            <h1 className="text-2xl font-bold">New password</h1>
            <p className="text-sm text-zinc-500">Choose a new password for your account</p>
          </div>
        </div>

        {done ? (
          <div className="space-y-4 rounded-xl border border-mint/20 bg-mint/5 p-5">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-mint" />
              <p className="font-medium text-mint">Password updated</p>
            </div>
            <p className="text-sm text-zinc-400">
              Your password has been changed successfully. You can now sign in with your new
              password.
            </p>
            <Link
              href="/login"
              className="block w-full rounded-lg bg-mint py-2.5 text-center font-medium text-canvas transition hover:brightness-110"
            >
              Sign in
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm text-zinc-400">New password</label>
              <div className="relative">
                <Lock
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full rounded-lg border border-line bg-panel pl-9 pr-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
                  placeholder="••••••••"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-zinc-400">Confirm password</label>
              <div className="relative">
                <Lock
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600"
                />
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  minLength={8}
                  className="w-full rounded-lg border border-line bg-panel pl-9 pr-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
                  placeholder="••••••••"
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
                  <Loader2 size={16} className="animate-spin" /> Updating...
                </>
              ) : (
                "Update password"
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="grid-bg flex min-h-screen items-center justify-center">
        <div className="skeleton h-8 w-8 rounded-full bg-white/10" />
      </div>
    }>
      <ResetPasswordContent />
    </Suspense>
  );
}
