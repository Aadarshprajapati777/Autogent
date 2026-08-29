"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Fact } from "@/lib/types";
import { Sparkles, Search } from "lucide-react";

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

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Memory</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Facts the agent has learned about your team and work.
      </p>

      <div className="mt-6 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search facts..."
          className="w-full rounded-lg border border-line bg-panel pl-9 pr-4 py-2.5 text-sm outline-none transition focus:border-mint/50"
        />
      </div>

      <div className="mt-6 space-y-2">
        {loading ? (
          <div className="skeleton h-20 rounded-lg bg-white/5" />
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No facts yet</p>
            <p className="mt-1 text-xs text-zinc-700">
              The agent will populate memory as it works.
            </p>
          </div>
        ) : (
          filtered.map((f) => (
            <div
              key={f.fact_id}
              className="rounded-lg border border-line bg-panel px-4 py-3"
            >
              <div className="flex items-center justify-between">
                <p className="text-sm">
                  <span className="font-medium text-mint">{f.subject}</span>{" "}
                  <span className="text-zinc-500">{f.predicate}</span>{" "}
                  <span>{f.value}</span>
                </p>
                <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-zinc-500">
                  {f.fact_kind}
                </span>
              </div>
              {f.topics && f.topics.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {f.topics.map((t) => (
                    <span
                      key={t}
                      className="rounded bg-mint/10 px-1.5 py-0.5 text-xs text-mint/70"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
