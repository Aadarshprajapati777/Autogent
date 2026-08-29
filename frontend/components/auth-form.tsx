"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { Sparkles } from "lucide-react";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { login, signup } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "signup") {
        await signup(name, email, password);
      } else {
        await login(email, password);
      }
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid-bg flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex items-center gap-3">
          <Sparkles className="h-7 w-7 text-mint" />
          <h1 className="text-2xl font-bold">
            {mode === "signup" ? "Create your account" : "Welcome back"}
          </h1>
        </div>
        <form onSubmit={submit} className="space-y-4">
          {mode === "signup" && (
            <div>
              <label className="mb-1.5 block text-sm text-zinc-400">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full rounded-lg border border-line bg-panel px-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
                placeholder="Ada Lovelace"
              />
            </div>
          )}
          <div>
            <label className="mb-1.5 block text-sm text-zinc-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-line bg-panel px-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm text-zinc-400">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full rounded-lg border border-line bg-panel px-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
              placeholder="********"
            />
          </div>
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-mint px-4 py-2.5 font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
          >
            {loading ? "Please wait..." : mode === "signup" ? "Sign up" : "Sign in"}
          </button>
        </form>
        <p className="text-center text-sm text-zinc-500">
          {mode === "signup" ? (
            <>
              Already have an account?{" "}
              <a href="/login" className="text-mint hover:underline">
                Sign in
              </a>
            </>
          ) : (
            <>
              New to Autogent?{" "}
              <a href="/signup" className="text-mint hover:underline">
                Create an account
              </a>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
