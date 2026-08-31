"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Task, Fact, Person } from "@/lib/types";
import {
  CheckSquare,
  Sparkles,
  Users,
  MessageSquare,
  ArrowRight,
  Clock,
  TrendingUp,
} from "lucide-react";
import { Card, StatCard, SectionTitle, Badge, Avatar, Skeleton } from "@/components/ui";

export default function DashboardPage() {
  const { workspace } = useWorkspace();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    Promise.all([
      api<{ count: number; tasks: Task[] }>(`/tasks?workspace_id=${workspace.id}`),
      api<{ count: number; facts: Fact[] }>(`/memory/facts?workspace_id=${workspace.id}`),
      api<{ count: number; people: Person[] }>(`/memory/people?workspace_id=${workspace.id}`),
    ])
      .then(([t, f, p]) => {
        setTasks(t.tasks);
        setFacts(f.facts);
        setPeople(p.people);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  const openTasks = tasks.filter((t) => t.state === "open" || t.state === "in_progress");
  const completedTasks = tasks.filter((t) => t.state === "completed");
  const blockedTasks = tasks.filter((t) => t.state === "blocked" || t.state === "overdue");
  const completionRate = tasks.length > 0 ? completedTasks.length / tasks.length : 0;

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2.5">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint/10">
          <TrendingUp size={18} className="text-mint" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Overview</h1>
          <p className="text-sm text-zinc-500">{workspace.name}</p>
        </div>
      </div>

      {/* Stats grid */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={CheckSquare}
          label="Open tasks"
          value={loading ? "—" : openTasks.length}
          sublabel={`${completedTasks.length} completed · ${blockedTasks.length} blocked`}
          accent="mint"
        />
        <StatCard
          icon={Sparkles}
          label="Memory facts"
          value={loading ? "—" : facts.length}
          sublabel="Agent knowledge base"
          accent="violet"
        />
        <StatCard
          icon={Users}
          label="People"
          value={loading ? "—" : people.length}
          sublabel="Team profiles"
          accent="blue"
        />
        <StatCard
          icon={MessageSquare}
          label="Completion"
          value={loading ? "—" : `${Math.round(completionRate * 100)}%`}
          sublabel={`${tasks.length} total tasks`}
          accent="amber"
        />
      </div>

      {/* Two-column content */}
      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        {/* Recent tasks — spans 2 cols */}
        <Card className="lg:col-span-2">
          <SectionTitle
            action={
              <Link href="/tasks" className="flex items-center gap-1 text-sm text-mint hover:underline">
                View all <ArrowRight size={14} />
              </Link>
            }
          >
            Recent tasks
          </SectionTitle>
          <div className="mt-4 space-y-2">
            {loading ? (
              <>
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </>
            ) : tasks.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-600">No tasks yet</p>
            ) : (
              tasks.slice(0, 6).map((t) => {
                const colorMap: Record<string, "zinc" | "blue" | "rose" | "mint" | "amber"> = {
                  open: "zinc",
                  in_progress: "blue",
                  blocked: "rose",
                  completed: "mint",
                  overdue: "amber",
                  cancelled: "zinc",
                };
                return (
                  <Link
                    key={t.id}
                    href="/tasks"
                    className="flex items-center gap-3 rounded-lg border border-line bg-white/[.02] px-3 py-2.5 transition hover:bg-white/[.04]"
                  >
                    <div
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        t.state === "completed" ? "bg-mint" :
                        t.state === "blocked" ? "bg-rose-500" :
                        t.state === "overdue" ? "bg-amber-500" :
                        t.state === "in_progress" ? "bg-blue-500" : "bg-zinc-600"
                      }`}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{t.title}</span>
                    {t.due_at && (
                      <span className="hidden items-center gap-1 text-xs text-zinc-600 sm:flex">
                        <Clock size={12} />
                        {new Date(t.due_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                      </span>
                    )}
                    <Badge color={colorMap[t.state] ?? "zinc"}>
                      {t.state.replace("_", " ")}
                    </Badge>
                  </Link>
                );
              })
            )}
          </div>
        </Card>

        {/* Recent memory */}
        <Card>
          <SectionTitle
            action={
              <Link href="/memory" className="flex items-center gap-1 text-sm text-mint hover:underline">
                All <ArrowRight size={14} />
              </Link>
            }
          >
            Recent memory
          </SectionTitle>
          <div className="mt-4 space-y-2">
            {loading ? (
              <>
                <Skeleton className="h-16" />
                <Skeleton className="h-16" />
              </>
            ) : facts.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-600">No facts yet</p>
            ) : (
              facts.slice(0, 5).map((f) => (
                <div
                  key={f.fact_id}
                  className="rounded-lg border border-line bg-white/[.02] px-3 py-2.5"
                >
                  <p className="text-sm leading-snug">
                    <span className="font-medium text-mint">{f.subject}</span>{" "}
                    <span className="text-zinc-500">{f.predicate}</span>{" "}
                    <span className="text-zinc-300">{f.value}</span>
                  </p>
                  {f.topics && f.topics.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {f.topics.slice(0, 3).map((t) => (
                        <span key={t} className="rounded bg-mint/10 px-1.5 py-0.5 text-[10px] text-mint/70">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Team preview */}
      {people.length > 0 && (
        <Card className="mt-6">
          <SectionTitle
            action={
              <Link href="/people" className="flex items-center gap-1 text-sm text-mint hover:underline">
                View all <ArrowRight size={14} />
              </Link>
            }
          >
            Team
          </SectionTitle>
          <div className="mt-4 flex flex-wrap gap-3">
            {people.slice(0, 8).map((p) => (
              <Link
                key={p.person_id ?? p.name}
                href="/people"
                className="flex items-center gap-2 rounded-xl border border-line bg-white/[.02] px-3 py-2 transition hover:bg-white/[.04]"
              >
                <Avatar name={p.name} size={32} />
                <div>
                  <p className="text-sm font-medium leading-tight">{p.name}</p>
                  <p className="text-xs text-zinc-500 leading-tight">{p.role}</p>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
