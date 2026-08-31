"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/components/workspace-provider";
import { useAuth } from "@/components/auth-provider";
import type { User } from "@/lib/types";
import {
  Settings,
  ShieldAlert,
  Zap,
  Activity,
  User as UserIcon,
  Mail,
  Clock,
  Save,
  Building2,
  Calendar,
} from "lucide-react";
import {
  PageHeader,
  EmptyState,
  Skeleton,
  Card,
  Badge,
  Avatar,
} from "@/components/ui";
import { cn } from "@/lib/utils";

interface EscalationRule {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  conditions: Record<string, unknown>;
  action: Record<string, unknown>;
}

const inputCls =
  "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm text-zinc-200 outline-none transition focus:border-mint/50 placeholder:text-zinc-600";

export default function SettingsPage() {
  const { workspace } = useWorkspace();
  const { user, refresh } = useAuth();
  const [rules, setRules] = useState<EscalationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState({
    display_name: "",
    timezone: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);

  const loadRules = () => {
    if (!workspace) return;
    setLoading(true);
    api<{ count: number; rules: EscalationRule[] }>(
      `/settings/escalations?workspace_id=${workspace.id}`,
    )
      .then((r) => setRules(r.rules))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadRules();
    // eslint-disable-next-line react-hooks/set-state-in-effect
  }, [workspace]);

  useEffect(() => {
    if (user) {
      setProfile({
        display_name: user.name ?? "",
        timezone: (user as User & { timezone?: string }).timezone ?? "",
      });
    }
  }, [user]);

  if (!workspace) return null;

  const toggle = async (rule: EscalationRule) => {
    try {
      await api(`/settings/escalations/${rule.id}?workspace_id=${workspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      loadRules();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    }
  };

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingProfile(true);
    setProfileMsg(null);
    try {
      await api("/auth/profile", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: profile.display_name.trim() || undefined,
          timezone: profile.timezone.trim() || undefined,
        }),
      });
      await refresh();
      setProfileMsg("Profile saved");
    } catch (err) {
      setProfileMsg(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingProfile(false);
    }
  };

  const enabledCount = rules.filter((r) => r.enabled).length;
  const sortedRules = [...rules].sort((a, b) => a.priority - b.priority);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        icon={Settings}
        title="Settings"
        subtitle="Account, workspace, and escalation configuration"
      />

      {/* ───────────── Account / Profile ───────────── */}
      <div className="mt-8">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint/10">
            <UserIcon size={18} className="text-mint" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Account</h2>
            <p className="text-sm text-zinc-500">Your user profile and identity</p>
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {/* Profile card */}
          <Card className="lg:col-span-2">
            <form onSubmit={saveProfile} className="space-y-4">
              <div className="flex items-center gap-4">
                <Avatar name={user?.name ?? "?"} size={56} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{user?.name ?? "—"}</p>
                  <p className="truncate text-sm text-zinc-500">{user?.email ?? "—"}</p>
                </div>
                <Badge color="mint">
                  <Calendar size={10} /> Free plan
                </Badge>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-600">
                    Display name
                  </label>
                  <input
                    value={profile.display_name}
                    onChange={(e) => setProfile({ ...profile, display_name: e.target.value })}
                    placeholder="Your name"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-600">
                    Timezone
                  </label>
                  <input
                    value={profile.timezone}
                    onChange={(e) => setProfile({ ...profile, timezone: e.target.value })}
                    placeholder="Asia/Kolkata"
                    className={inputCls}
                  />
                </div>
              </div>

              {/* Read-only identity */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-600">
                    Email
                  </label>
                  <div className="flex items-center gap-2 rounded-lg border border-line bg-panel/50 px-3 py-2 text-sm text-zinc-400">
                    <Mail size={14} className="text-zinc-600" />
                    <span className="truncate">{user?.email ?? "—"}</span>
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-600">
                    User ID
                  </label>
                  <div className="flex items-center gap-2 rounded-lg border border-line bg-panel/50 px-3 py-2 text-xs text-zinc-500">
                    <span className="truncate font-mono">{user?.id ?? "—"}</span>
                  </div>
                </div>
              </div>

              {profileMsg && (
                <p className={cn(
                  "text-sm",
                  profileMsg === "Profile saved" ? "text-mint" : "text-rose-400",
                )}>
                  {profileMsg}
                </p>
              )}

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={savingProfile}
                  className="flex items-center gap-2 rounded-lg bg-mint px-4 py-2 text-sm font-semibold text-black transition hover:bg-mint/90 disabled:opacity-50"
                >
                  <Save size={14} />
                  {savingProfile ? "Saving..." : "Save profile"}
                </button>
              </div>
            </form>
          </Card>

          {/* Quick stats */}
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-600">
              Quick stats
            </p>
            <div className="mt-3 space-y-3">
              <Stat
                icon={Building2}
                label="Workspaces"
                value={user?.workspaces?.length ?? 0}
              />
              <Stat
                icon={ShieldAlert}
                label="Escalation rules"
                value={rules.length}
              />
              <Stat
                icon={Zap}
                label="Active rules"
                value={enabledCount}
                accent="text-mint"
              />
              <Stat
                icon={Clock}
                label="Plan"
                value="Free"
              />
            </div>
          </Card>
        </div>
      </div>

      {/* ───────────── Workspaces ───────────── */}
      <div className="mt-10">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-blue-500/10">
            <Building2 size={18} className="text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Workspaces</h2>
            <p className="text-sm text-zinc-500">Organizations you belong to</p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {user?.workspaces?.map((w) => (
            <Card key={w.id} className="flex items-center gap-4" hover>
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mint/10 font-bold text-mint">
                {w.name[0]}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{w.name}</p>
                <p className="truncate text-xs text-zinc-600 font-mono">{w.id}</p>
              </div>
              <Badge color={w.role === "owner" ? "mint" : "zinc"}>
                {w.role}
              </Badge>
            </Card>
          )) ?? (
            <Skeleton className="h-16" />
          )}
        </div>
      </div>

      {/* ───────────── Escalation rules ───────────── */}
      <div className="mt-10">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-amber-500/10">
            <ShieldAlert size={18} className="text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Escalation rules</h2>
            <p className="text-sm text-zinc-500">
              Rules the agent uses to escalate issues automatically
            </p>
          </div>
        </div>

        {/* Summary */}
        <div className="mt-4 flex gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
            <Zap size={16} className="text-mint" />
            <span className="text-sm text-zinc-400">Active</span>
            <span className="text-sm font-bold">{enabledCount}</span>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
            <Activity size={16} className="text-zinc-500" />
            <span className="text-sm text-zinc-400">Total</span>
            <span className="text-sm font-bold">{rules.length}</span>
          </div>
        </div>

        {/* Rules */}
        <div className="mt-4 space-y-3">
          {loading ? (
            <>
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </>
          ) : rules.length === 0 ? (
            <EmptyState
              icon={ShieldAlert}
              title="No escalation rules"
              description="Escalation rules define when the agent should alert founders about risks like overdue tasks or silent engineers."
            />
          ) : (
            sortedRules.map((r) => (
              <Card key={r.id} className="flex items-center gap-4" hover>
                {/* Priority indicator */}
                <div className={cn(
                  "grid h-10 w-10 shrink-0 place-items-center rounded-xl font-bold",
                  r.priority <= 1 ? "bg-rose-500/15 text-rose-400" :
                  r.priority <= 2 ? "bg-amber-500/15 text-amber-400" :
                  "bg-zinc-500/15 text-zinc-400",
                )}>
                  P{r.priority}
                </div>

                {/* Rule info */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{r.name}</p>
                    {r.enabled && (
                      <span className="flex items-center gap-1 rounded-md bg-mint/10 px-1.5 py-0.5 text-[10px] font-medium text-mint">
                        <span className="h-1.5 w-1.5 rounded-full bg-mint" /> Active
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-zinc-600">
                    {Object.entries(r.conditions)
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join(" · ")}
                  </p>
                </div>

                {/* Toggle */}
                <button
                  onClick={() => toggle(r)}
                  className={cn(
                    "relative h-6 w-11 shrink-0 rounded-full transition",
                    r.enabled ? "bg-mint" : "bg-zinc-700",
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform",
                      r.enabled ? "translate-x-5" : "translate-x-0.5",
                    )}
                  />
                </button>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  accent = "text-zinc-200",
}: {
  icon: typeof UserIcon;
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/[.03]">
        <Icon size={15} className="text-zinc-500" />
      </div>
      <div className="flex-1">
        <p className="text-xs text-zinc-600">{label}</p>
        <p className={cn("text-sm font-semibold", accent)}>{value}</p>
      </div>
    </div>
  );
}
