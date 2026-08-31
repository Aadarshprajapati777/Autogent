"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import {
  BarChart3,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Users,
  Zap,
  TrendingUp,
  Activity,
  Target,
  Flame,
  CalendarDays,
  RefreshCw,
} from "lucide-react";
import {
  PageHeader,
  Card,
  Badge,
  StatCard,
  ProgressBar,
  Skeleton,
  Avatar,
  SectionTitle,
  EmptyState,
} from "@/components/ui";
import { cn } from "@/lib/utils";

interface AnalyticsData {
  summary: {
    total_tasks: number;
    completed_tasks: number;
    open_tasks: number;
    blocked_tasks: number;
    overdue_count: number;
    completion_rate: number;
    total_people: number;
    active_projects: number;
    open_alerts: number;
    meetings_this_week: number;
  };
  task_metrics: {
    total: number;
    open: number;
    in_progress: number;
    blocked: number;
    completed: number;
    cancelled: number;
    overdue: number;
  };
  task_velocity: { date: string; created: number; completed: number }[];
  overdue_tasks: {
    id: string;
    title: string;
    due_at: string | null;
    state: string;
    days_overdue: number;
  }[];
  projects: {
    id: string;
    name: string;
    description: string | null;
    status: string;
    deadline: string | null;
    total_tasks: number;
    completed_tasks: number;
    blocked_tasks: number;
    progress: number;
    health: string;
  }[];
  team_skills: {
    total_people: number;
    skills: { skill: string; count: number; people: string[] }[];
    people: {
      name: string;
      role: string;
      title: string | null;
      skills: string[];
      integrations_linked: number;
      avatar_url: string | null;
      timezone: string | null;
    }[];
  };
  person_reliability: {
    name: string;
    role: string;
    commitments: number;
    completed: number;
    blockers: number;
    reliability_score: number | null;
  }[];
  alerts: {
    id: string;
    type: string;
    subject: string;
    severity: string;
    message: string;
    project: string | null;
    person: string | null;
    created_at: string | null;
  }[];
  blocked_tasks: {
    id: string;
    title: string;
    state: string;
    source: string;
    due_at: string | null;
  }[];
  meeting_stats: { total: number; this_week: number; completed: number };
  activity_timeline: { date: string; facts: number }[];
  integration_coverage: {
    total_people: number;
    slack: number;
    github: number;
    jira: number;
    linear: number;
    email: number;
  };
}

const healthConfig: Record<string, { color: "mint" | "amber" | "rose" | "zinc"; label: string }> = {
  on_track: { color: "mint", label: "On Track" },
  at_risk: { color: "amber", label: "At Risk" },
  blocked: { color: "rose", label: "Blocked" },
  planning: { color: "zinc", label: "Planning" },
};

const severityConfig: Record<string, { color: "rose" | "amber" | "zinc"; label: string }> = {
  high: { color: "rose", label: "High" },
  medium: { color: "amber", label: "Medium" },
  low: { color: "zinc", label: "Low" },
};

export default function AnalyticsPage() {
  const { workspace } = useWorkspace();
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(() => {
    if (!workspace) return;
    setLoading(true);
    api<AnalyticsData>(`/analytics?workspace_id=${workspace.id}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspace]);

  const refresh = useCallback(() => {
    if (!workspace) return;
    setRefreshing(true);
    api<AnalyticsData>(`/analytics?workspace_id=${workspace.id}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setRefreshing(false));
  }, [workspace]);

  useEffect(() => {
    load();
  }, [load]);

  if (!workspace) return null;

  if (loading) {
    return (
      <div className="p-6 lg:p-8">
        <Skeleton className="h-9 w-64" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 lg:p-8">
        <EmptyState
          icon={BarChart3}
          title="No analytics data yet"
          description="Connect integrations and create tasks to see analytics here."
        />
      </div>
    );
  }

  const s = data.summary;
  const maxVelocity = Math.max(
    ...data.task_velocity.map((v) => Math.max(v.created, v.completed)),
    1,
  );
  const maxActivity = Math.max(...data.activity_timeline.map((a) => a.facts), 1);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={BarChart3}
        title="Analytics"
        subtitle="Project health, team capabilities, and bottlenecks at a glance"
        action={
          <button
            onClick={refresh}
            disabled={refreshing}
            className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm text-zinc-400 transition hover:border-mint/50 hover:text-mint disabled:opacity-50"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        }
      />

      {/* ─── Top stat cards ─── */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Target}
          label="Completion Rate"
          value={`${Math.round(s.completion_rate * 100)}%`}
          sublabel={`${s.completed_tasks} of ${s.total_tasks} tasks done`}
          accent="mint"
        />
        <StatCard
          icon={Users}
          label="Team Members"
          value={s.total_people}
          sublabel={`${s.active_projects} active projects`}
          accent="blue"
        />
        <StatCard
          icon={AlertTriangle}
          label="Open Alerts"
          value={s.open_alerts}
          sublabel={`${s.overdue_count} overdue tasks`}
          accent={s.open_alerts > 0 ? "rose" : "blue"}
        />
        <StatCard
          icon={CalendarDays}
          label="Meetings This Week"
          value={s.meetings_this_week}
          sublabel={`${data.meeting_stats.total} total meetings`}
          accent="violet"
        />
      </div>

      {/* ─── Task velocity chart + Task breakdown ─── */}
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {/* Velocity chart */}
        <Card className="lg:col-span-2">
          <SectionTitle>
            <span className="flex items-center gap-2">
              <TrendingUp size={16} className="text-mint" />
              Task Velocity
            </span>
          </SectionTitle>
          <div className="mt-6 flex h-40 items-end gap-1.5">
            {data.task_velocity.map((v) => (
              <div key={v.date} className="flex flex-1 flex-col items-center gap-1">
                <div className="flex w-full items-end justify-center gap-0.5" style={{ height: "120px" }}>
                  <div
                    className="w-1/2 rounded-t bg-blue-500/60 transition-all duration-500"
                    style={{ height: `${(v.created / maxVelocity) * 100}%`, minHeight: v.created > 0 ? "4px" : "0" }}
                    title={`Created: ${v.created}`}
                  />
                  <div
                    className="w-1/2 rounded-t bg-mint transition-all duration-500"
                    style={{ height: `${(v.completed / maxVelocity) * 100}%`, minHeight: v.completed > 0 ? "4px" : "0" }}
                    title={`Completed: ${v.completed}`}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div className="flex items-center gap-4 text-xs text-zinc-500">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-blue-500/60" /> Created
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-mint" /> Completed
              </span>
            </div>
            <span className="text-xs text-zinc-600">Last 14 days</span>
          </div>
        </Card>

        {/* Task breakdown */}
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <CheckCircle2 size={16} className="text-mint" />
              Task Status
            </span>
          </SectionTitle>
          <div className="mt-4 space-y-3">
            <TaskBarRow label="Completed" count={data.task_metrics.completed} total={data.task_metrics.total} color="mint" />
            <TaskBarRow label="In Progress" count={data.task_metrics.in_progress} total={data.task_metrics.total} color="blue" />
            <TaskBarRow label="Open" count={data.task_metrics.open} total={data.task_metrics.total} color="blue" />
            <TaskBarRow label="Blocked" count={data.task_metrics.blocked} total={data.task_metrics.total} color="rose" />
            <TaskBarRow label="Overdue" count={data.task_metrics.overdue} total={data.task_metrics.total} color="amber" />
          </div>
        </Card>
      </div>

      {/* ─── Project progress ─── */}
      <div className="mt-6">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Target size={16} className="text-mint" />
            Project Progress
          </span>
        </SectionTitle>
        {data.projects.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              icon={Target}
              title="No projects yet"
              description="Ask the agent to create a project to track progress here."
            />
          </div>
        ) : (
          <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.projects.map((p) => {
              const hc = healthConfig[p.health] ?? healthConfig.planning;
              return (
                <Card key={p.id} hover>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium leading-snug">{p.name}</p>
                      {p.description && (
                        <p className="mt-1 line-clamp-2 text-xs text-zinc-500">{p.description}</p>
                      )}
                    </div>
                    <Badge color={hc.color}>{hc.label}</Badge>
                  </div>

                  <div className="mt-4">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-500">Progress</span>
                      <span className="font-medium text-zinc-300">{Math.round(p.progress * 100)}%</span>
                    </div>
                    <ProgressBar
                      value={p.progress}
                      color={hc.color === "mint" ? "mint" : hc.color === "amber" ? "amber" : hc.color === "rose" ? "rose" : "blue"}
                      className="mt-1.5"
                    />
                  </div>

                  <div className="mt-4 flex items-center gap-4 border-t border-line pt-3 text-xs">
                    <span className="text-zinc-500">
                      <span className="font-medium text-zinc-300">{p.completed_tasks}</span>/{p.total_tasks} tasks
                    </span>
                    {p.blocked_tasks > 0 && (
                      <span className="flex items-center gap-1 text-rose-400">
                        <AlertTriangle size={11} /> {p.blocked_tasks} blocked
                      </span>
                    )}
                    {p.deadline && (
                      <span className="flex items-center gap-1 text-zinc-500">
                        <Clock size={11} /> {p.deadline}
                      </span>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* ─── Team skills + Reliability ─── */}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {/* Who is good at what */}
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <Zap size={16} className="text-amber-400" />
              Team Skills
            </span>
          </SectionTitle>
          {data.team_skills.skills.length === 0 ? (
            <p className="mt-4 text-sm text-zinc-500">
              No skills recorded yet. The agent learns skills from meetings and Slack onboarding.
            </p>
          ) : (
            <div className="mt-4 space-y-2.5">
              {data.team_skills.skills.map((sk) => (
                <div key={sk.skill} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 truncate text-sm text-zinc-300">{sk.skill}</span>
                  <div className="flex-1">
                    <ProgressBar value={sk.count / data.team_skills.total_people} color="amber" />
                  </div>
                  <span className="text-xs text-zinc-500">{sk.count}</span>
                  <span className="hidden text-xs text-zinc-600 sm:inline">{sk.people.join(", ")}</span>
                </div>
              ))}
            </div>
          )}

          {/* Integration coverage */}
          <div className="mt-5 border-t border-line pt-4">
            <p className="mb-2 text-xs font-medium text-zinc-500">Integration Coverage</p>
            <div className="grid grid-cols-5 gap-2">
              {[
                { label: "Slack", value: data.integration_coverage.slack, total: data.integration_coverage.total_people },
                { label: "GitHub", value: data.integration_coverage.github, total: data.integration_coverage.total_people },
                { label: "Jira", value: data.integration_coverage.jira, total: data.integration_coverage.total_people },
                { label: "Linear", value: data.integration_coverage.linear, total: data.integration_coverage.total_people },
                { label: "Email", value: data.integration_coverage.email, total: data.integration_coverage.total_people },
              ].map((ic) => (
                <div key={ic.label} className="rounded-lg border border-line bg-white/[.02] p-2 text-center">
                  <p className="text-sm font-bold text-zinc-200">{ic.value}</p>
                  <p className="text-[10px] text-zinc-600">{ic.label}</p>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {/* Reliability leaderboard */}
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <Flame size={16} className="text-rose-400" />
              Team Reliability
            </span>
          </SectionTitle>
          {data.person_reliability.length === 0 ? (
            <p className="mt-4 text-sm text-zinc-500">
              No reliability data yet. The agent tracks commitments and completions over time.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {data.person_reliability.map((p, i) => (
                <div key={p.name} className="flex items-center gap-3">
                  <span className="w-5 text-center text-xs font-bold text-zinc-600">{i + 1}</span>
                  <Avatar name={p.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{p.name}</p>
                    <p className="text-xs text-zinc-600">
                      {p.completed} completed · {p.commitments} commitments
                      {p.blockers > 0 && ` · ${p.blockers} blockers`}
                    </p>
                  </div>
                  {p.reliability_score !== null ? (
                    <div className="text-right">
                      <span className={cn(
                        "text-lg font-bold",
                        p.reliability_score >= 0.7 ? "text-mint" :
                        p.reliability_score >= 0.4 ? "text-amber-400" : "text-rose-400"
                      )}>
                        {Math.round(p.reliability_score * 100)}%
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-zinc-600">—</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* ─── Bottlenecks + Alerts ─── */}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {/* Where the project is stuck */}
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <AlertTriangle size={16} className="text-rose-400" />
              Bottlenecks
            </span>
          </SectionTitle>
          {data.blocked_tasks.length === 0 && data.overdue_tasks.length === 0 ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-mint">
              <CheckCircle2 size={16} />
              No blocked or overdue tasks. Everything is flowing.
            </div>
          ) : (
            <div className="mt-4 space-y-2">
              {data.overdue_tasks.slice(0, 5).map((t) => (
                <div key={t.id} className="flex items-center gap-3 rounded-lg border border-rose-500/20 bg-rose-500/5 p-3">
                  <AlertTriangle size={14} className="shrink-0 text-rose-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{t.title}</p>
                    <p className="text-xs text-zinc-500">
                      {t.days_overdue} day{t.days_overdue !== 1 ? "s" : ""} overdue
                    </p>
                  </div>
                  <Badge color="rose">Overdue</Badge>
                </div>
              ))}
              {data.blocked_tasks.slice(0, 5).map((t) => (
                <div key={t.id} className="flex items-center gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                  <AlertTriangle size={14} className="shrink-0 text-amber-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{t.title}</p>
                    <p className="text-xs text-zinc-500">{t.source === "memory_task" ? "Extracted task" : "Task"}</p>
                  </div>
                  <Badge color="amber">Blocked</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Active alerts */}
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <Activity size={16} className="text-violet-400" />
              Risk Alerts
            </span>
          </SectionTitle>
          {data.alerts.length === 0 ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-mint">
              <CheckCircle2 size={16} />
              No active alerts. The agent is monitoring for risks.
            </div>
          ) : (
            <div className="mt-4 space-y-2">
              {data.alerts.slice(0, 8).map((a) => {
                const sc = severityConfig[a.severity] ?? severityConfig.medium;
                return (
                  <div key={a.id} className="rounded-lg border border-line bg-white/[.02] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium">{a.subject || a.type}</p>
                      <Badge color={sc.color}>{sc.label}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">{a.message}</p>
                    {a.person && (
                      <p className="mt-1.5 text-xs text-zinc-600">
                        Person: <span className="text-zinc-400">{a.person}</span>
                        {a.project && <> · Project: <span className="text-zinc-400">{a.project}</span></>}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* ─── Activity timeline ─── */}
      <div className="mt-6">
        <Card>
          <SectionTitle>
            <span className="flex items-center gap-2">
              <Activity size={16} className="text-blue-400" />
              Knowledge Activity
            </span>
          </SectionTitle>
          <p className="mt-1 text-xs text-zinc-600">Facts learned by the agent per day</p>
          <div className="mt-4 flex h-24 items-end gap-1.5">
            {data.activity_timeline.map((a) => (
              <div
                key={a.date}
                className="flex-1 rounded-t bg-blue-500/40 transition-all duration-500 hover:bg-blue-500/70"
                style={{
                  height: `${(a.facts / maxActivity) * 100}%`,
                  minHeight: a.facts > 0 ? "4px" : "0",
                }}
                title={`${a.date}: ${a.facts} facts`}
              />
            ))}
          </div>
          <div className="mt-2 flex justify-between text-xs text-zinc-600">
            <span>14 days ago</span>
            <span>Today</span>
          </div>
        </Card>
      </div>

      {/* ─── Team members grid ─── */}
      <div className="mt-6">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Users size={16} className="text-blue-400" />
            Team Members
          </span>
        </SectionTitle>
        {data.team_skills.people.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              icon={Users}
              title="No team members yet"
              description="Connect Slack and sync people to see your team here."
            />
          </div>
        ) : (
          <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.team_skills.people.map((p) => (
              <Card key={p.name} hover>
                <div className="flex items-center gap-3">
                  <Avatar name={p.name} size={44} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{p.name}</p>
                    <p className="truncate text-xs text-zinc-500">
                      {p.title || p.role}
                    </p>
                  </div>
                </div>
                {p.skills.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {p.skills.slice(0, 4).map((sk, i) => (
                      <span key={i} className="rounded-md bg-white/[.06] px-1.5 py-0.5 text-[10px] text-zinc-400">
                        {sk}
                      </span>
                    ))}
                    {p.skills.length > 4 && (
                      <span className="text-[10px] text-zinc-600">+{p.skills.length - 4}</span>
                    )}
                  </div>
                )}
                <div className="mt-3 flex items-center gap-3 border-t border-line pt-3 text-xs text-zinc-600">
                  {p.timezone && <span>{p.timezone}</span>}
                  <span className="ml-auto flex items-center gap-1">
                    <span className="font-medium text-zinc-400">{p.integrations_linked}</span> integrations
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TaskBarRow({
  label,
  count,
  total,
  color,
}: {
  label: string;
  count: number;
  total: number;
  color: "mint" | "blue" | "amber" | "rose";
}) {
  const pct = total > 0 ? count / total : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-400">{label}</span>
        <span className="font-medium text-zinc-300">{count}</span>
      </div>
      <ProgressBar value={pct} color={color} className="mt-1" />
    </div>
  );
}
