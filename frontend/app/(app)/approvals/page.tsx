"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

interface Candidate {
  id: string;
  ref: string;
  title: string;
  description: string | null;
  owner_name: string | null;
  due_at: string | null;
  confidence: number;
  state: string;
  task_id: string | null;
}

export default function ApprovalsPage() {
  const { workspace } = useWorkspace();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const load = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; candidates: Candidate[] }>(
      `/approvals?workspace_id=${workspace.id}&state=pending`,
    )
      .then((r) => setCandidates(r.candidates))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [workspace]);

  if (!workspace) return null;

  const review = async (id: string, decision: "approve" | "reject") => {
    setActing(id);
    try {
      await api(`/approvals/${id}/review`, {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          decision,
        }),
      });
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setActing(null);
    }
  };

  const stateColors: Record<string, string> = {
    pending: "bg-amber-500/15 text-amber-400",
    auto_approved: "bg-mint/15 text-mint",
    materialized: "bg-mint/15 text-mint",
    rejected: "bg-rose-500/15 text-rose-400",
    edited: "bg-blue-500/15 text-blue-400",
  };

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Approvals</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Task candidates extracted from meetings. Review and approve them.
      </p>

      <div className="mt-6 space-y-3">
        {loading ? (
          <div className="skeleton h-24 rounded-xl bg-white/5" />
        ) : candidates.length === 0 ? (
          <div className="rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No pending approvals</p>
          </div>
        ) : (
          candidates.map((c) => (
            <div
              key={c.id}
              className="rounded-xl border border-line bg-panel p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-zinc-600">{c.ref}</span>
                    <span
                      className={cn(
                        "rounded-md px-2 py-0.5 text-xs font-medium",
                        stateColors[c.state] ?? "bg-zinc-500/15 text-zinc-400",
                      )}
                    >
                      {c.state.replace("_", " ")}
                    </span>
                  </div>
                  <p className="mt-2 font-medium">{c.title}</p>
                  {c.description && (
                    <p className="mt-1 text-sm text-zinc-500">{c.description}</p>
                  )}
                  <div className="mt-2 flex gap-4 text-xs text-zinc-600">
                    {c.owner_name && <span>Owner: {c.owner_name}</span>}
                    {c.due_at && (
                      <span>Due: {new Date(c.due_at).toLocaleDateString()}</span>
                    )}
                    <span>Confidence: {Math.round(c.confidence * 100)}%</span>
                  </div>
                </div>
                {c.state === "pending" && (
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => review(c.id, "approve")}
                      disabled={acting === c.id}
                      className="rounded-lg bg-mint px-3 py-1.5 text-sm font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => review(c.id, "reject")}
                      disabled={acting === c.id}
                      className="rounded-lg border border-line px-3 py-1.5 text-sm text-zinc-400 transition hover:border-rose-500/50 hover:text-rose-400 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
