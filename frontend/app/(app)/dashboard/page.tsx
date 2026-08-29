"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Task, Fact } from "@/lib/types";
import { CheckSquare, Sparkles, Users, MessageSquare } from "lucide-react";

export default function DashboardPage() {
  const { workspace } = useWorkspace();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    Promise.all([
      api<{ count: number; tasks: Task[] }>(`/tasks?workspace_id=${workspace.id}`),
      api<{ count: number; facts: Fact[] }>(`/memory/facts?workspace_id=${workspace.id}`),
    ])
      .then(([t, f]) => {
        setTasks(t.tasks.slice(0, 5));
        setFacts(f.facts.slice(0, 5));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-2xl font-bold">Overview</h1>
      <p className="mt-1 text-sm text-zinc-500">{workspace.name}</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={CheckSquare} label="Open tasks" value={tasks.length} />
        <StatCard icon={Sparkles} label="Memory facts" value={facts.length} />
        <StatCard icon={Users} label="People" value="—" />
        <StatCard icon={MessageSquare} label="Agent runs" value="—" />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-line bg-panel p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Recent tasks</h2>
            <Link href="/tasks" className="text-sm text-mint hover:underline">
              View all
            </Link>
          </div>
          <div className="mt-4 space-y-2">
            {loading ? (
              <div className="skeleton h-16 rounded-lg bg-white/5" />
            ) : tasks.length === 0 ? (
              <p className="text-sm text-zinc-600">No tasks yet</p>
            ) : (
              tasks.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded-lg border border-line bg-white/[.02] px-3 py-2"
                >
                  <span className="truncate text-sm">{t.title}</span>
                  <span className="text-xs text-zinc-500">{t.state}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-xl border border-line bg-panel p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Recent memory</h2>
            <Link href="/memory" className="text-sm text-mint hover:underline">
              View all
            </Link>
          </div>
          <div className="mt-4 space-y-2">
            {loading ? (
              <div className="skeleton h-16 rounded-lg bg-white/5" />
            ) : facts.length === 0 ? (
              <p className="text-sm text-zinc-600">No facts yet</p>
            ) : (
              facts.map((f) => (
                <div
                  key={f.fact_id}
                  className="rounded-lg border border-line bg-white/[.02] px-3 py-2"
                >
                  <p className="text-sm">
                    <span className="text-mint">{f.subject}</span>{" "}
                    <span className="text-zinc-500">{f.predicate}</span>{" "}
                    {f.value}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-xl border border-line bg-panel p-5">
      <Icon size={20} className="text-mint" />
      <p className="mt-3 text-2xl font-bold">{value}</p>
      <p className="text-sm text-zinc-500">{label}</p>
    </div>
  );
}
