"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { ShieldCheck, Check, X, User, Calendar, Gauge } from "lucide-react";
import { PageHeader, EmptyState, Skeleton, Badge, Card, ProgressBar } from "@/components/ui";

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

  const stateColors: Record<string, "amber" | "mint" | "rose" | "blue"> = {
    pending: "amber",
    auto_approved: "mint",
    materialized: "mint",
    rejected: "rose",
    edited: "blue",
  };

  const confidenceColor = (c: number) =>
    c >= 0.8 ? "mint" : c >= 0.5 ? "amber" : "rose";

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={ShieldCheck}
        title="Approvals"
        subtitle="Task candidates extracted from meetings — review and approve them"
      />

      {loading ? (
        <div className="mt-6 space-y-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : candidates.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={ShieldCheck}
            title="No pending approvals"
            description="When the agent extracts tasks from meetings, they'll appear here for your review."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {candidates.map((c) => (
            <Card key={c.id} className="flex flex-col">
              {/* Header */}
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-zinc-600">{c.ref}</span>
                <Badge color={stateColors[c.state] ?? "zinc"}>
                  {c.state.replace("_", " ")}
                </Badge>
              </div>

              {/* Title + description */}
              <p className="mt-3 font-medium leading-snug">{c.title}</p>
              {c.description && (
                <p className="mt-1.5 text-sm leading-relaxed text-zinc-500">{c.description}</p>
              )}

              {/* Meta */}
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-600">
                {c.owner_name && (
                  <span className="flex items-center gap-1">
                    <User size={12} /> {c.owner_name}
                  </span>
                )}
                {c.due_at && (
                  <span className="flex items-center gap-1">
                    <Calendar size={12} /> {new Date(c.due_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </span>
                )}
              </div>

              {/* Confidence */}
              <div className="mt-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="flex items-center gap-1 text-xs text-zinc-500">
                    <Gauge size={12} /> Confidence
                  </span>
                  <span className="text-xs font-medium text-zinc-400">
                    {Math.round(c.confidence * 100)}%
                  </span>
                </div>
                <ProgressBar value={c.confidence} color={confidenceColor(c.confidence)} />
              </div>

              {/* Actions */}
              {c.state === "pending" && (
                <div className="mt-4 flex gap-2 border-t border-line pt-4">
                  <button
                    onClick={() => review(c.id, "approve")}
                    disabled={acting === c.id}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-mint px-3 py-2 text-sm font-medium text-canvas transition hover:brightness-110 disabled:opacity-50"
                  >
                    <Check size={16} /> Approve
                  </button>
                  <button
                    onClick={() => review(c.id, "reject")}
                    disabled={acting === c.id}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-zinc-400 transition hover:border-rose-500/50 hover:text-rose-400 disabled:opacity-50"
                  >
                    <X size={16} /> Reject
                  </button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
