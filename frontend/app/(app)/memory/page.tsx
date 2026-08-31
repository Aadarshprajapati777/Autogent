"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Fact } from "@/lib/types";
import { Sparkles, Search, Brain, User, Building2, Target } from "lucide-react";
import { PageHeader, EmptyState, Skeleton, Badge } from "@/components/ui";
import { cn } from "@/lib/utils";

const kindConfig: Record<string, { icon: typeof Brain; color: string; bg: string }> = {
  person: { icon: User, color: "text-blue-400", bg: "bg-blue-500/10" },
  project: { icon: Building2, color: "text-violet-400", bg: "bg-violet-500/10" },
  task: { icon: Target, color: "text-amber-400", bg: "bg-amber-500/10" },
  commitment: { icon: Target, color: "text-mint", bg: "bg-mint/10" },
  fact: { icon: Brain, color: "text-mint", bg: "bg-mint/10" },
};

export default function MemoryPage() {
  const { workspace } = useWorkspace();
  const [facts, setFacts] = useState<Fact[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; facts: Fact[] }>(
      `/memory/facts?workspace_id=${workspace.id}`,
    )
      .then((r) => setFacts(r.facts))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  const filtered = query
    ? facts.filter((f) =>
        [f.subject, f.predicate, f.value, ...(f.topics || [])]
          .join(" ")
          .toLowerCase()
          .includes(query.toLowerCase()),
      )
    : facts;

  // Group by kind
  const kindGroups = filtered.reduce<Record<string, Fact[]>>((acc, f) => {
    const kind = f.fact_kind || "fact";
    if (!acc[kind]) acc[kind] = [];
    acc[kind].push(f);
    return acc;
  }, {});

  const kindCounts = Object.entries(kindGroups)
    .map(([kind, items]) => ({ kind, count: items.length }))
    .sort((a, b) => b.count - a.count);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={Sparkles}
        title="Memory"
        subtitle="Facts the agent has learned about your team and work"
      />

      {/* Search + stats */}
      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search facts..."
            className="w-full rounded-lg border border-line bg-panel pl-9 pr-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {kindCounts.map(({ kind, count }) => {
            const cfg = kindConfig[kind] || kindConfig.fact;
            return (
              <div key={kind} className={cn("flex items-center gap-1.5 rounded-lg px-2.5 py-1.5", cfg.bg)}>
                <cfg.icon size={14} className={cfg.color} />
                <span className="text-xs text-zinc-400">{kind}</span>
                <span className="text-xs font-bold text-zinc-300">{count}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Facts grid */}
      {loading ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={Sparkles}
            title={query ? "No matching facts" : "No facts yet"}
            description="The agent populates memory as it works — chatting, checking in, and ingesting meetings."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((f) => {
            const cfg = kindConfig[f.fact_kind] || kindConfig.fact;
            return (
              <div
                key={f.fact_id}
                className="group rounded-xl border border-line bg-panel p-4 transition hover:border-white/10 hover:bg-white/[.02]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", cfg.bg)}>
                    <cfg.icon size={16} className={cfg.color} />
                  </div>
                  <Badge color="zinc">{f.fact_kind}</Badge>
                </div>
                <p className="mt-3 text-sm leading-snug">
                  <span className="font-medium text-mint">{f.subject}</span>{" "}
                  <span className="text-zinc-500">{f.predicate}</span>{" "}
                  <span className="text-zinc-200">{f.value}</span>
                </p>
                {f.topics && f.topics.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {f.topics.map((t) => (
                      <span
                        key={t}
                        className="rounded bg-mint/10 px-1.5 py-0.5 text-[10px] text-mint/70"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                {f.confidence < 1.0 && (
                  <div className="mt-3 flex items-center gap-1.5">
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div
                        className="h-full rounded-full bg-mint"
                        style={{ width: `${Math.round(f.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-600">{Math.round(f.confidence * 100)}%</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
