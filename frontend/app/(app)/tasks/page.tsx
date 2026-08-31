"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import type { Task } from "@/lib/types";
import { CheckSquare, Clock, AlertCircle, CircleDot, CheckCircle2, AlertTriangle } from "lucide-react";
import { PageHeader, EmptyState, Skeleton, Card } from "@/components/ui";
import { cn } from "@/lib/utils";

const columns = [
  { key: "open", label: "Open", icon: CircleDot, color: "zinc" as const },
  { key: "in_progress", label: "In Progress", icon: Clock, color: "blue" as const },
  { key: "blocked", label: "Blocked", icon: AlertCircle, color: "rose" as const },
  { key: "overdue", label: "Overdue", icon: AlertTriangle, color: "amber" as const },
  { key: "completed", label: "Completed", icon: CheckCircle2, color: "mint" as const },
];

export default function TasksPage() {
  const { workspace } = useWorkspace();
  const [tasks, setTasks] = useState<Task[]>([]);
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

  const tasksByState = (state: string) => tasks.filter((t) => t.state === state);
  const otherTasks = tasks.filter((t) => !columns.some((c) => c.key === t.state));

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={CheckSquare}
        title="Tasks"
        subtitle="Work items tracked across your workspace"
      />

      {/* Summary bar */}
      <div className="mt-6 flex flex-wrap gap-3">
        {columns.map((col) => {
          const count = tasksByState(col.key).length;
          return (
            <div
              key={col.key}
              className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2"
            >
              <col.icon size={16} className={cn(
                col.color === "mint" && "text-mint",
                col.color === "blue" && "text-blue-400",
                col.color === "rose" && "text-rose-400",
                col.color === "amber" && "text-amber-400",
                col.color === "zinc" && "text-zinc-400",
              )} />
              <span className="text-sm text-zinc-400">{col.label}</span>
              <span className="text-sm font-bold">{count}</span>
            </div>
          );
        })}
      </div>

      {/* Kanban board */}
      {loading ? (
        <div className="mt-6 grid gap-4 lg:grid-cols-5">
          {columns.map((c) => (
            <Skeleton key={c.key} className="h-48" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={CheckSquare}
            title="No tasks yet"
            description="Tasks appear here once the agent creates them from conversations, meetings, or project kickoffs."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-5">
          {columns.map((col) => {
            const colTasks = tasksByState(col.key);
            return (
              <div key={col.key} className="space-y-3">
                <div className="flex items-center gap-2 px-1">
                  <col.icon size={15} className={cn(
                    col.color === "mint" && "text-mint",
                    col.color === "blue" && "text-blue-400",
                    col.color === "rose" && "text-rose-400",
                    col.color === "amber" && "text-amber-400",
                    col.color === "zinc" && "text-zinc-400",
                  )} />
                  <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    {col.label}
                  </span>
                  <span className="ml-auto rounded-md bg-white/5 px-1.5 py-0.5 text-xs text-zinc-500">
                    {colTasks.length}
                  </span>
                </div>
                {colTasks.map((t) => (
                  <TaskCard key={t.id} task={t} />
                ))}
                {colTasks.length === 0 && (
                  <div className="rounded-lg border border-dashed border-line/50 py-8 text-center">
                    <p className="text-xs text-zinc-700">Empty</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Other states */}
      {otherTasks.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">Other</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {otherTasks.map((t) => (
              <TaskCard key={t.id} task={t} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TaskCard({ task }: { task: Task }) {
  const isOverdue = task.state === "overdue" || (task.due_at && new Date(task.due_at) < new Date() && task.state !== "completed");
  return (
    <Card hover className="p-4">
      <p className="text-sm font-medium leading-snug">{task.title}</p>
      <div className="mt-3 flex items-center justify-between">
        {task.due_at ? (
          <span className={cn(
            "flex items-center gap-1 text-xs",
            isOverdue ? "text-amber-400" : "text-zinc-600",
          )}>
            <Clock size={12} />
            {new Date(task.due_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
          </span>
        ) : (
          <span className="text-xs text-zinc-700">No due date</span>
        )}
        {task.priority > 0 && (
          <span className="text-xs text-zinc-600">P{task.priority}</span>
        )}
      </div>
    </Card>
  );
}
