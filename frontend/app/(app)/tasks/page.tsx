"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Task } from "@/lib/types";
import { CheckSquare } from "lucide-react";
import { cn } from "@/lib/utils";

const stateColors: Record<string, string> = {
  open: "bg-zinc-500/15 text-zinc-400",
  in_progress: "bg-blue-500/15 text-blue-400",
  blocked: "bg-rose-500/15 text-rose-400",
  completed: "bg-mint/15 text-mint",
  cancelled: "bg-zinc-500/15 text-zinc-600",
  overdue: "bg-amber-500/15 text-amber-400",
};

export default function TasksPage() {
  const { workspace } = useWorkspace();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; tasks: Task[] }>(
      `/tasks?workspace_id=${workspace.id}`,
    )
      .then((r) => setTasks(r.tasks))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  if (!workspace) return null;

  const filtered =
    filter === "all" ? tasks : tasks.filter((t) => t.state === filter);

  return (
    <div className="p-6 lg:p-8">
      <div className="flex items-center gap-2">
        <CheckSquare className="h-5 w-5 text-mint" />
        <h1 className="text-2xl font-bold">Tasks</h1>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        Work items tracked across your workspace.
      </p>

      <div className="mt-6 flex gap-2 overflow-x-auto">
        {["all", "open", "in_progress", "blocked", "completed", "overdue"].map(
          (s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition",
                filter === s
                  ? "bg-mint text-canvas"
                  : "border border-line bg-panel text-zinc-400 hover:text-zinc-200",
              )}
            >
              {s.replace("_", " ")}
            </button>
          ),
        )}
      </div>

      <div className="mt-4 space-y-2">
        {loading ? (
          <div className="skeleton h-16 rounded-lg bg-white/5" />
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-line bg-panel p-8 text-center">
            <p className="text-sm text-zinc-600">No tasks</p>
          </div>
        ) : (
          filtered.map((t) => (
            <div
              key={t.id}
              className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{t.title}</p>
                {t.due_at && (
                  <p className="mt-0.5 text-xs text-zinc-600">
                    Due {new Date(t.due_at).toLocaleDateString()}
                  </p>
                )}
              </div>
              <span
                className={cn(
                  "ml-3 shrink-0 rounded-md px-2 py-0.5 text-xs font-medium",
                  stateColors[t.state] ?? "bg-zinc-500/15 text-zinc-400",
                )}
              >
                {t.state.replace("_", " ")}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
